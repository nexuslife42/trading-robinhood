"""Approval and durable order state. No model has an approval endpoint."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from .broker import BrokerAdapter
from .models import OrderIntent, OrderResult, Policy, Preview, aware, digest
from .policy import evaluate
from .state import ExecutionError, State, encode

__all__ = ["ExecutionError", "Executor"]


class Executor:
    def __init__(self, state: State, broker: BrokerAdapter, policy: Policy, *, release: str):
        self.state, self.broker, self.policy, self.release = state, broker, policy, release
        self._halted = False
        if broker.mode != policy.mode:
            raise ExecutionError("Broker mode does not match policy")
        # A crash may have happened after the network accepted an order.
        with state.lock(), state.transaction():
            state.connection.execute(
                "UPDATE orders SET status='proposed',approval=NULL WHERE status='approved'"
            )
            unresolved = any(
                row["status"] in ("submitting", "unknown", "cancel_pending")
                for row in state.orders()
            )
            if unresolved:
                state.set_halt(True)

    def _running(self) -> None:
        if self._halted or self.state.halted:
            raise ExecutionError("Trading halted; reconcile before manual resume")

    def _check(self, intent: OrderIntent, now: datetime) -> Preview:
        aware(now)
        snapshot = self.broker.snapshot(now)
        quote = self.broker.quote(intent.instrument, now)
        usage = self.state.usage(intent.account, now, self.policy.fee_buffer)
        decision = evaluate(intent, self.policy, quote, snapshot, usage, now)
        if not decision.allowed:
            raise ExecutionError("Policy rejected: " + ", ".join(decision.reasons))
        preview = self.broker.preview(intent, now)
        if preview.intent_digest != intent.digest() or preview.quote_digest != quote.digest():
            raise ExecutionError("Preview does not match order and quote")
        return preview

    def _binding(self, intent: OrderIntent, preview: Preview) -> str:
        return digest(
            {
                "intent": intent.digest(),
                "preview": preview.digest(),
                "policy": self.policy.digest(),
                "release": self.release,
            }
        )

    def propose(self, intent: OrderIntent, now: datetime) -> str:
        with self.state.lock():
            self._running()
            self._check(intent, now)
            key = str(intent.request_id)
            try:
                with self.state.transaction():
                    self.state.connection.execute(
                        "INSERT INTO orders(id,account,intent,status,created_at) "
                        "VALUES (?,?,?,?,?)",
                        (
                            key,
                            intent.account,
                            intent.model_dump_json(),
                            "proposed",
                            now.astimezone(UTC).isoformat(),
                        ),
                    )
                    self.state.event(key, "proposed", now)
            except sqlite3.IntegrityError as exc:
                raise ExecutionError("duplicate request ID") from exc
            return key

    def review(self, key: str, now: datetime) -> dict[str, Any]:
        row = self.state.get_order(key)
        intent = OrderIntent.model_validate_json(row["intent"])
        preview = self._check(intent, now)
        return {
            "intent": intent.model_dump(mode="json"),
            "preview": preview.model_dump(mode="json"),
            "policy_digest": self.policy.digest(),
            "release": self.release,
            "binding": self._binding(intent, preview),
        }

    def approve(self, key: str, now: datetime, *, expected_binding: str | None = None) -> None:
        """Operator-only operation; never registered as an MCP tool."""
        with self.state.lock():
            self._running()
            row = self.state.get_order(key)
            if row["status"] not in ("proposed", "approved"):
                raise ExecutionError("Order cannot receive another approval")
            intent = OrderIntent.model_validate_json(row["intent"])
            binding = self._binding(intent, self._check(intent, now))
            if expected_binding is not None and binding != expected_binding:
                raise ExecutionError("Order changed since operator review")
            approval = encode(
                {
                    "binding": binding,
                    "expires_at": (
                        now + timedelta(seconds=self.policy.approval_ttl_seconds)
                    ).isoformat(),
                    "approved_at": now.isoformat(),
                }
            )
            with self.state.transaction():
                self.state.connection.execute(
                    "UPDATE orders SET status='approved',approval=? WHERE id=?", (approval, key)
                )
                self.state.event(key, "approved", now)

    def execute(self, key: str, now: datetime) -> OrderResult:
        with self.state.lock():
            self._running()
            row = self.state.get_order(key)
            if row["status"] != "approved" or not row["approval"]:
                raise ExecutionError("Unconsumed approval required")
            intent = OrderIntent.model_validate_json(row["intent"])
            approval = json.loads(row["approval"])
            if (
                not datetime.fromisoformat(approval["approved_at"])
                <= now
                < datetime.fromisoformat(approval["expires_at"])
            ):
                raise ExecutionError("approval expired or clock moved backwards")
            if approval["binding"] != self._binding(intent, self._check(intent, now)):
                raise ExecutionError("approval no longer matches current context")
            with self.state.transaction():
                self.state.connection.execute(
                    "UPDATE orders SET status='submitting',approval=NULL,submitted_at=? WHERE id=?",
                    (now.astimezone(UTC).isoformat(), key),
                )
                self.state.event(key, "submitting", now)
            # This commit must happen before the network call; never retry this call here.
            try:
                result = self.broker.submit(intent, now)
                self._record(key, result, now)
                return result
            except Exception as exc:
                self._unknown(key, now)
                raise ExecutionError(
                    "Submission outcome unknown; reconcile before any further action"
                ) from exc

    def _record(self, key: str, result: OrderResult, now: datetime) -> None:
        row = self.state.get_order(key)
        intent = OrderIntent.model_validate_json(row["intent"])
        previous_fill = Decimal(row["filled_quantity"])
        if not previous_fill <= result.filled_quantity <= intent.quantity:
            raise ExecutionError("Invalid cumulative fill quantity")
        if result.status == "filled" and result.filled_quantity != intent.quantity:
            raise ExecutionError("Filled status without full quantity")
        if result.status == "partial" and not 0 < result.filled_quantity < intent.quantity:
            raise ExecutionError("Invalid partial fill")
        if result.status != "unknown" and not result.broker_id:
            raise ExecutionError("Missing broker order ID")
        if row["broker_id"] and result.broker_id and row["broker_id"] != result.broker_id:
            raise ExecutionError("Broker identity changed")
        if row["status"] in ("filled", "canceled", "rejected") and result.status != row["status"]:
            raise ExecutionError("Terminal order state changed")
        with self.state.transaction():
            if result.status == "unknown":
                self.state.set_halt(True)
            self.state.connection.execute(
                "UPDATE orders SET status=?,broker_id=?,filled_quantity=? WHERE id=?",
                (
                    result.status,
                    result.broker_id or row["broker_id"],
                    str(result.filled_quantity),
                    key,
                ),
            )
            self.state.event(key, result.status, now)

    def _unknown(self, key: str, now: datetime) -> None:
        # Preserve the halt in this process even when disk writes cannot record it.
        self._halted = True
        with self.state.transaction():
            self.state.set_halt(True)
            self.state.connection.execute(
                "UPDATE orders SET status='unknown',approval=NULL WHERE id=?", (key,)
            )
            self.state.event(key, "unknown", now)

    def reconcile(self, key: str, now: datetime) -> OrderResult:
        with self.state.lock():
            row = self.state.get_order(key)
            if not row["submitted_at"]:
                raise ExecutionError("Order has not been submitted")
            if self._halted or self.state.halted:
                # Once storage recovers, preserve the halt through reconciliation and restart.
                with self.state.transaction():
                    self.state.set_halt(True)
            try:
                result = self.broker.lookup(key, now)
                self._record(key, result, now)
                return result
            except Exception as exc:
                self._unknown(key, now)
                raise ExecutionError("Reconciliation failed; order remains unresolved") from exc

    def cancel(self, key: str, now: datetime) -> OrderResult:
        with self.state.lock():
            row = self.state.get_order(key)
            if row["status"] not in ("open", "partial"):
                raise ExecutionError("Reconcile order before cancellation")
            with self.state.transaction():
                self.state.connection.execute(
                    "UPDATE orders SET status='cancel_pending' WHERE id=?", (key,)
                )
                self.state.event(key, "cancel_pending", now)
            try:
                result = self.broker.cancel(key, now)
                self._record(key, result, now)
                return result
            except Exception as exc:
                self._unknown(key, now)
                raise ExecutionError("Cancellation outcome unknown; reconcile") from exc

    def halt(self, reason: str, now: datetime) -> None:
        self._halted = True
        with self.state.lock(), self.state.transaction():
            self.state.set_halt(True)
            self.state.connection.execute(
                "UPDATE orders SET status='proposed',approval=NULL WHERE status='approved'"
            )
            self.state.event(None, "halted", now, reason)

    def resume(self, now: datetime) -> None:
        with self.state.lock(), self.state.transaction():
            if any(
                row["status"] in ("submitting", "unknown", "cancel_pending")
                for row in self.state.orders()
            ):
                raise ExecutionError("Cannot resume with unresolved orders")
            self.state.set_halt(False)
            self.state.event(None, "resumed", now)
        self._halted = False
