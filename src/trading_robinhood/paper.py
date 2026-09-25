"""Deterministic long-equity limit-order simulator, never a Robinhood connection."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from .models import AccountSnapshot, OrderIntent, OrderResult, Preview, Quote, aware
from .state import State, encode


class PaperBroker:
    mode = "paper"

    def __init__(
        self,
        state: State,
        *,
        account: str,
        cash: Decimal,
        fee: Decimal = Decimal(0),
        slippage_bps: Decimal = Decimal(0),
    ):
        if not all(v.is_finite() and v >= 0 for v in (cash, fee, slippage_bps)):
            raise ValueError("Invalid simulation cost")
        if slippage_bps >= 10000:
            raise ValueError("Slippage must be below 10000 basis points")
        self.state, self.account = state, account
        self.fee, self.slippage_bps = fee, slippage_bps
        state.connection.execute(
            "INSERT OR IGNORE INTO paper_accounts VALUES (?,?,?)", (account, str(cash), "{}")
        )

    def set_quote(self, quote: Quote) -> None:
        row = self.state.connection.execute(
            "SELECT payload FROM paper_quotes WHERE instrument=?", (quote.instrument,)
        ).fetchone()
        if row and Quote.model_validate_json(row[0]).observed_at > quote.observed_at:
            raise ValueError("Quote time must be monotonic")
        self.state.connection.execute(
            "INSERT OR REPLACE INTO paper_quotes VALUES (?,?)",
            (quote.instrument, quote.model_dump_json()),
        )

    def quote(self, instrument: str, now: datetime) -> Quote:
        row = self.state.connection.execute(
            "SELECT payload FROM paper_quotes WHERE instrument=?", (instrument,)
        ).fetchone()
        if row is None:
            raise ValueError("No quote")
        result = Quote.model_validate_json(row[0])
        if result.observed_at > now:
            raise ValueError("Cannot read a future quote")
        return result

    def _balances(self) -> tuple[Decimal, dict[str, Decimal]]:
        row = self.state.connection.execute(
            "SELECT cash,positions FROM paper_accounts WHERE account=?", (self.account,)
        ).fetchone()
        return Decimal(row[0]), {k: Decimal(v) for k, v in json.loads(row[1]).items()}

    def _save(self, cash: Decimal, positions: dict[str, Decimal]) -> None:
        self.state.connection.execute(
            "UPDATE paper_accounts SET cash=?,positions=? WHERE account=?",
            (str(cash), encode({k: str(v) for k, v in positions.items()}), self.account),
        )

    def snapshot(self, now: datetime) -> AccountSnapshot:
        aware(now)
        with self.state.transaction():
            cash, positions = self._balances()
            rows = self.state.connection.execute(
                "SELECT id,amount,due FROM settlements WHERE account=?", (self.account,)
            ).fetchall()
            for row in rows:
                if datetime.fromisoformat(row["due"]) <= now:
                    cash += Decimal(row["amount"])
                    self.state.connection.execute(
                        "DELETE FROM settlements WHERE id=?", (row["id"],)
                    )
            self._save(cash, positions)
        return AccountSnapshot(
            account=self.account, buying_power=cash, positions=positions, observed_at=now
        )

    def preview(self, intent: OrderIntent, now: datetime) -> Preview:
        if intent.account != self.account or intent.asset_class != "equity":
            raise ValueError("Unsupported simulator account or asset class")
        return Preview(
            intent_digest=intent.digest(),
            quote_digest=self.quote(intent.instrument, now).digest(),
            warnings=("Simulation only; synthetic fills are not executable quotes",),
        )

    def submit(self, intent: OrderIntent, now: datetime) -> OrderResult:
        self.preview(intent, now)
        existing = self.state.connection.execute(
            "SELECT intent FROM paper_orders WHERE id=?", (str(intent.request_id),)
        ).fetchone()
        if existing:
            if existing[0] != intent.model_dump_json():
                raise ValueError("Conflicting request ID")
            return self.lookup(str(intent.request_id), now)
        self.state.connection.execute(
            "INSERT INTO paper_orders(id,intent,status,created_at) VALUES (?,?,?,?)",
            (
                str(intent.request_id),
                intent.model_dump_json(),
                "open",
                now.astimezone(UTC).isoformat(),
            ),
        )
        return self.lookup(str(intent.request_id), now)

    def lookup(self, request_id: str, now: datetime) -> OrderResult:
        row = self.state.connection.execute(
            "SELECT * FROM paper_orders WHERE id=?", (request_id,)
        ).fetchone()
        if row is None:
            return OrderResult(broker_id="", status="unknown")
        return OrderResult(
            broker_id="paper-" + request_id, status=row["status"], filled_quantity=row["filled"]
        )

    def cancel(self, request_id: str, now: datetime) -> OrderResult:
        self.state.connection.execute(
            "UPDATE paper_orders SET status='canceled' WHERE id=? AND status IN ('open','partial')",
            (request_id,),
        )
        return self.lookup(request_id, now)

    def orders(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.state.connection.execute("SELECT * FROM paper_orders ORDER BY rowid")
        ]

    def advance(self, quote: Quote, liquidity: Decimal) -> list[OrderResult]:
        if not liquidity.is_finite() or liquidity < 0:
            raise ValueError("Invalid liquidity")
        self.set_quote(quote)
        results: list[OrderResult] = []
        with self.state.transaction():
            cash, positions = self._balances()
            for row in self.orders():
                intent = OrderIntent.model_validate_json(row["intent"])
                if (
                    intent.account != self.account
                    or intent.instrument != quote.instrument
                    or row["status"] not in ("open", "partial")
                ):
                    continue
                created = datetime.fromisoformat(row["created_at"])
                if quote.observed_at <= created:
                    continue
                if quote.observed_at.astimezone(UTC).date() > created.date():
                    self.state.connection.execute(
                        "UPDATE paper_orders SET status='canceled' WHERE id=?", (row["id"],)
                    )
                    results.append(self.lookup(row["id"], quote.observed_at))
                    continue
                if liquidity == 0 or not quote.tradable or not quote.market_open:
                    continue
                factor = self.slippage_bps / Decimal(10000)
                price = (
                    quote.ask * (1 + factor) if intent.side == "buy" else quote.bid * (1 - factor)
                )
                if (intent.side == "buy" and price > intent.limit_price) or (
                    intent.side == "sell" and price < intent.limit_price
                ):
                    continue
                filled = Decimal(row["filled"])
                quantity = min(intent.quantity - filled, liquidity)
                fee = Decimal(0) if row["fee_paid"] else self.fee
                holding = positions.get(intent.instrument, Decimal(0))
                if (intent.side == "buy" and quantity * price + fee > cash) or (
                    intent.side == "sell" and (quantity > holding or fee > cash)
                ):
                    self.state.connection.execute(
                        "UPDATE paper_orders SET status='rejected' WHERE id=?", (row["id"],)
                    )
                    results.append(self.lookup(row["id"], quote.observed_at))
                    continue
                cash -= fee
                if intent.side == "buy":
                    cash -= quantity * price
                    positions[intent.instrument] = holding + quantity
                else:
                    positions[intent.instrument] = holding - quantity
                    due = quote.observed_at + timedelta(days=1)
                    while due.weekday() >= 5:
                        due += timedelta(days=1)
                    self.state.connection.execute(
                        "INSERT INTO settlements(account,amount,due) VALUES (?,?,?)",
                        (self.account, str(quantity * price), due.isoformat()),
                    )
                filled += quantity
                liquidity -= quantity
                status = "filled" if filled == intent.quantity else "partial"
                self.state.connection.execute(
                    "UPDATE paper_orders SET status=?,filled=?,fee_paid=1 WHERE id=?",
                    (status, str(filled), row["id"]),
                )
                results.append(self.lookup(row["id"], quote.observed_at))
            self._save(cash, positions)
        return results
