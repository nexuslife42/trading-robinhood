"""Replay explicit test orders through the same policy and execution engine."""

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from .execution import Executor
from .models import Model, Money, OrderIntent, Policy, Positive, Quote, digest
from .paper import PaperBroker
from .state import State


class DatasetMetadata(Model):
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)
    timezone: Literal["UTC"]
    adjustments: str = Field(min_length=1)
    asset_class: Literal["equity"]
    corporate_actions: Literal["none"]
    synthetic: bool


class Tick(Model):
    at: AwareDatetime
    instrument: str
    bid: Positive
    ask: Positive
    liquidity: Money
    tradable: bool = True
    market_open: bool = True


class ScheduledOrder(OrderIntent):
    at: AwareDatetime


class Dataset(Model):
    metadata: DatasetMetadata
    ticks: tuple[Tick, ...] = Field(min_length=1)
    orders: tuple[ScheduledOrder, ...]


def replay(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 10_000_000:
        raise ValueError("Replay fixture exceeds 10 MB; partition larger datasets")
    dataset = Dataset.model_validate_json(path.read_text())
    times = [tick.at for tick in dataset.ticks]
    if times != sorted(set(times)):
        raise ValueError("Replay ticks must have strictly increasing timestamps")
    if any(order.at not in times for order in dataset.orders):
        raise ValueError("Each scripted order must have an exact input tick")
    instruments = tuple(sorted({tick.instrument for tick in dataset.ticks}))
    policy = Policy(
        accounts=("paper",),
        instruments=instruments,
        max_order_value=Decimal("1000"),
        max_daily_value=Decimal("10000"),
        max_daily_orders=100,
        max_open_orders=10,
        fee_buffer=Decimal("1"),
    )
    fills: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="rh-replay-") as temporary:
        state = State(Path(temporary) / "replay.sqlite3")
        try:
            broker = PaperBroker(state, account="paper", cash=Decimal("1000"), fee=Decimal("1"))
            executor = Executor(state, broker, policy, release="synthetic-replay-v1")
            for tick in dataset.ticks:
                quote = Quote(
                    instrument=tick.instrument,
                    bid=tick.bid,
                    ask=tick.ask,
                    observed_at=tick.at,
                    tradable=tick.tradable,
                    market_open=tick.market_open,
                )
                for result in broker.advance(quote, tick.liquidity):
                    key = result.broker_id.removeprefix("paper-")
                    executor.reconcile(key, tick.at)
                    fills.append({"at": tick.at.isoformat(), **result.model_dump(mode="json")})
                for scheduled in dataset.orders:
                    if scheduled.at == tick.at:
                        intent = OrderIntent.model_validate(scheduled.model_dump(exclude={"at"}))
                        key = executor.propose(intent, tick.at)
                        # Explicit scripted approvals are permitted only in this paper-only harness.
                        executor.approve(key, tick.at)
                        executor.execute(key, tick.at)
            snapshot = broker.snapshot(times[-1])
            orders = [
                {
                    "request_id": row["id"],
                    "status": row["status"],
                    "filled_quantity": row["filled_quantity"],
                }
                for row in state.orders()
            ]
            return {
                "mode": "paper",
                "dataset_digest": digest(dataset.model_dump(mode="json")),
                "metadata": dataset.metadata.model_dump(),
                "cash": str(snapshot.buying_power),
                "positions": {key: str(value) for key, value in snapshot.positions.items()},
                "orders": orders,
                "fills": fills,
                "assumptions": "Equity limit DAY orders; next-tick fills; $1/order fee; "
                "zero slippage; shared tick liquidity; weekday T+1 sale settlement; "
                "no holidays or corporate actions",
            }
        finally:
            state.close()
