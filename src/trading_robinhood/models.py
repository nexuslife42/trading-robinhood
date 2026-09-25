"""Validated, canonical values shared by simulation and execution."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def decimal_input(value: Any) -> Any:
    if isinstance(value, (float, bool)):
        raise ValueError("Use decimal strings, integers, or Decimal; floats are not accepted")
    return value


Money = Annotated[Decimal, BeforeValidator(decimal_input), Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[Decimal, BeforeValidator(decimal_input), Field(gt=0, allow_inf_nan=False)]
Alias = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class OrderIntent(Model):
    request_id: UUID
    account: Alias
    instrument: Alias
    asset_class: Literal["equity", "option", "crypto"] = "equity"
    side: Literal["buy", "sell"]
    quantity: Positive
    limit_price: Positive
    order_type: Literal["limit"] = "limit"
    time_in_force: Literal["day"] = "day"

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.limit_price


class Quote(Model):
    instrument: Alias
    bid: Positive
    ask: Positive
    observed_at: AwareDatetime
    tradable: bool = True
    market_open: bool = True

    @model_validator(mode="after")
    def valid_spread(self) -> "Quote":
        if self.bid > self.ask:
            raise ValueError("Crossed quote")
        return self


class AccountSnapshot(Model):
    account: Alias
    buying_power: Money
    positions: dict[str, Money] = Field(default_factory=dict)
    observed_at: AwareDatetime


class Policy(Model):
    version: str = "1"
    mode: Literal["paper", "live"] = "paper"
    live_enabled: bool = False
    accounts: tuple[Alias, ...] = ()
    instruments: tuple[Alias, ...] = ()
    max_order_value: Money = Decimal(0)
    max_daily_value: Money = Decimal(0)
    max_daily_orders: int = Field(default=0, ge=0, strict=True)
    max_open_orders: int = Field(default=0, ge=0, strict=True)
    fee_buffer: Money = Decimal(0)
    max_data_age_seconds: int = Field(default=30, gt=0, le=300, strict=True)
    approval_ttl_seconds: int = Field(default=60, gt=0, le=300, strict=True)


class Usage(Model):
    reserved_cash: Money = Decimal(0)
    reserved_positions: dict[str, Money] = Field(default_factory=dict)
    daily_value: Money = Decimal(0)
    daily_orders: int = 0
    open_orders: int = 0


class PolicyDecision(Model):
    allowed: bool
    reasons: tuple[str, ...]
    policy_version: str
    reserve_cash: Money = Decimal(0)


class Preview(Model):
    intent_digest: str
    quote_digest: str
    warnings: tuple[str, ...] = ()


OrderStatus = Literal["open", "partial", "filled", "canceled", "rejected", "unknown"]


class OrderResult(Model):
    broker_id: str
    status: OrderStatus
    filled_quantity: Money = Decimal(0)


def aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
