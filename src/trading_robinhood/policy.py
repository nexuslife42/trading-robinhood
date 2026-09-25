"""Deterministic policy decisions; model text has no authority here."""

from datetime import datetime
from decimal import Decimal

from .models import AccountSnapshot, OrderIntent, Policy, PolicyDecision, Quote, Usage, aware


def evaluate(
    order: OrderIntent,
    policy: Policy,
    quote: Quote,
    snapshot: AccountSnapshot,
    usage: Usage,
    now: datetime,
) -> PolicyDecision:
    aware(now)
    reasons: list[str] = []
    if policy.mode == "live":
        # Deliberate certification gate: no authenticated execution contract is approved yet.
        reasons.append("live_not_certified")
    if order.account not in policy.accounts:
        reasons.append("account_not_allowed")
    if snapshot.account != order.account:
        reasons.append("account_mismatch")
    if order.instrument not in policy.instruments:
        reasons.append("instrument_not_allowed")
    if quote.instrument != order.instrument:
        reasons.append("quote_mismatch")
    if order.asset_class != "equity":
        reasons.append("unsupported_asset_class")
    for label, observed_at in [("quote", quote.observed_at), ("account", snapshot.observed_at)]:
        age = (now - observed_at).total_seconds()
        if not 0 <= age <= policy.max_data_age_seconds:
            reasons.append(f"{label}_stale")
    if not quote.tradable:
        reasons.append("not_tradable")
    if not quote.market_open:
        reasons.append("market_closed")
    if order.notional > policy.max_order_value:
        reasons.append("order_limit")
    if usage.daily_value + order.notional > policy.max_daily_value:
        reasons.append("daily_value_limit")
    if usage.daily_orders >= policy.max_daily_orders:
        reasons.append("daily_order_limit")
    if usage.open_orders >= policy.max_open_orders:
        reasons.append("open_order_limit")
    reserve = order.notional + policy.fee_buffer if order.side == "buy" else Decimal(0)
    if reserve > snapshot.buying_power - usage.reserved_cash:
        reasons.append("buying_power")
    if order.side == "sell":
        available = snapshot.positions.get(order.instrument, Decimal(0))
        available -= usage.reserved_positions.get(order.instrument, Decimal(0))
        if order.quantity > available:
            reasons.append("position_limit")
        if policy.fee_buffer > snapshot.buying_power - usage.reserved_cash:
            reasons.append("fee_buying_power")
    return PolicyDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        policy_version=policy.version,
        reserve_cash=reserve,
    )
