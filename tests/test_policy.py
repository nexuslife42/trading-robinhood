from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from trading_robinhood.models import AccountSnapshot, OrderIntent, Policy, Quote, Usage
from trading_robinhood.policy import evaluate

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


def order(**changes):
    return OrderIntent.model_validate(
        {
            "request_id": "11111111-1111-4111-8111-111111111111",
            "account": "paper",
            "instrument": "SYNTH",
            "side": "buy",
            "quantity": "2",
            "limit_price": "10",
            **changes,
        }
    )


def policy(**changes):
    return Policy.model_validate(
        {
            "accounts": ["paper"],
            "instruments": ["SYNTH"],
            "max_order_value": "100",
            "max_daily_value": "200",
            "max_daily_orders": 3,
            "max_open_orders": 2,
            "fee_buffer": "1",
            **changes,
        }
    )


def quote(**changes):
    return Quote.model_validate(
        {
            "instrument": "SYNTH",
            "bid": "9",
            "ask": "10",
            "observed_at": NOW,
            **changes,
        }
    )


def snapshot(**changes):
    return AccountSnapshot.model_validate(
        {
            "account": "paper",
            "buying_power": "1000",
            "positions": {"SYNTH": "10"},
            "observed_at": NOW,
            **changes,
        }
    )


def test_defaults_deny_order():
    result = evaluate(order(), Policy(), quote(), snapshot(), Usage(), NOW)
    assert not result.allowed
    assert "account_not_allowed" in result.reasons
    assert "order_limit" in result.reasons


def test_valid_paper_order_reserves_notional_and_fee():
    result = evaluate(order(), policy(), quote(), snapshot(), Usage(), NOW)
    assert result.allowed
    assert result.reserve_cash == Decimal("21")


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"account": "other"}, "account_mismatch"),
        ({"instrument": "OTHER"}, "instrument_not_allowed"),
        ({"quantity": "11"}, "order_limit"),
        ({"asset_class": "option"}, "unsupported_asset_class"),
    ],
)
def test_order_rejections(changes, reason):
    result = evaluate(order(**changes), policy(), quote(), snapshot(), Usage(), NOW)
    assert not result.allowed
    assert reason in result.reasons


@pytest.mark.parametrize("age", [31, -1])
def test_stale_or_future_quote_rejected(age):
    result = evaluate(
        order(), policy(), quote(observed_at=NOW - timedelta(seconds=age)), snapshot(), Usage(), NOW
    )
    assert "quote_stale" in result.reasons


def test_snapshot_staleness_and_market_closed_rejected():
    result = evaluate(
        order(),
        policy(),
        quote(market_open=False),
        snapshot(observed_at=NOW - timedelta(seconds=40)),
        Usage(),
        NOW,
    )
    assert {"account_stale", "market_closed"} <= set(result.reasons)


def test_pending_orders_reserve_cash_and_daily_capacity():
    usage = Usage(reserved_cash="990", daily_value="190", daily_orders=3, open_orders=2)
    result = evaluate(order(), policy(), quote(), snapshot(), usage, NOW)
    assert {"buying_power", "daily_value_limit", "daily_order_limit", "open_order_limit"} <= set(
        result.reasons
    )


def test_sell_cannot_short_or_reuse_reserved_shares():
    result = evaluate(
        order(side="sell", quantity="2"),
        policy(),
        quote(),
        snapshot(),
        Usage(reserved_positions={"SYNTH": "9"}),
        NOW,
    )
    assert "position_limit" in result.reasons


def test_live_policy_does_not_unlock_unverified_execution():
    result = evaluate(
        order(), policy(mode="live", live_enabled=True), quote(), snapshot(), Usage(), NOW
    )
    assert "live_not_certified" in result.reasons


@pytest.mark.parametrize("value", [0, "-1", "NaN", "Infinity", 0.1, True])
def test_invalid_money_cannot_enter_order(value):
    with pytest.raises(ValidationError):
        order(quantity=value)


def test_naive_time_and_extra_fields_rejected():
    with pytest.raises(ValidationError):
        quote(observed_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        order(approve=True)


@given(st.decimals(min_value="0.01", max_value="1000", places=2))
def test_values_over_limit_never_allowed(quantity):
    result = evaluate(order(quantity=quantity), policy(), quote(), snapshot(), Usage(), NOW)
    if quantity * Decimal("10") > Decimal("100"):
        assert not result.allowed
