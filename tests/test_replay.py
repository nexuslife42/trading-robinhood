import json
from decimal import Decimal

import pytest

from trading_robinhood.replay import replay


def write_dataset(tmp_path, *, future=False, missing=False):
    path = tmp_path / "ticks.json"
    document = {
        "metadata": {
            "source": "synthetic",
            "license": "project-owned",
            "timezone": "UTC",
            "adjustments": "none",
            "asset_class": "equity",
            "corporate_actions": "none",
            "synthetic": True,
        },
        "ticks": [
            {
                "at": "2026-09-24T14:00:00Z",
                "instrument": "SYNTH",
                "bid": "9",
                "ask": "10",
                "liquidity": "1",
            },
            {
                "at": "2026-09-24T14:01:00Z",
                "instrument": "SYNTH",
                "bid": "9",
                "ask": "10",
                "liquidity": "1",
            },
            {
                "at": "2026-09-24T14:02:00Z",
                "instrument": "SYNTH",
                "bid": "9",
                "ask": "10",
                "liquidity": "1",
            },
        ],
        "orders": [
            {
                "at": "2026-09-24T14:00:00Z",
                "request_id": "11111111-1111-4111-8111-111111111111",
                "account": "paper",
                "instrument": "SYNTH",
                "side": "buy",
                "quantity": "2",
                "limit_price": "10",
            }
        ],
    }
    if future:
        document["ticks"].reverse()
    if missing:
        document["metadata"].pop("license")
    path.write_text(json.dumps(document))
    return path


def test_replay_is_repeatable_and_does_not_fill_on_order_tick(tmp_path):
    path = write_dataset(tmp_path)
    first = replay(path)
    second = replay(path)
    assert first == second
    assert first["cash"] == "979"
    assert first["positions"] == {"SYNTH": "2"}
    assert first["orders"][0]["status"] == "filled"
    assert first["orders"][0]["filled_quantity"] == "2"
    assert first["fills"][0]["at"] == "2026-09-24T14:01:00+00:00"
    assert Decimal(first["cash"]) >= 0


@pytest.mark.parametrize("changes", [{"future": True}, {"missing": True}])
def test_replay_rejects_unsound_dataset(tmp_path, changes):
    with pytest.raises(ValueError):
        replay(write_dataset(tmp_path, **changes))
