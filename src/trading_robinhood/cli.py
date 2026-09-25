"""Small operator CLI. Connected discovery and live execution are separate gates."""

import argparse
import asyncio
import json
import os
import sys
import tomllib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .execution import ExecutionError, Executor
from .models import OrderIntent, Policy, Quote
from .paper import PaperBroker
from .release import build_manifest, verify_manifest
from .replay import replay
from .state import State


def policy_from(path: Path | None) -> Policy:
    return Policy.model_validate(tomllib.loads(path.read_text())) if path else Policy()


def output(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="rh", description="Guarded personal trading foundation")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    serve = commands.add_parser("serve")
    serve.add_argument("--state", type=Path, default=Path(".state/paper.sqlite3"))
    serve.add_argument("--policy", type=Path)
    discover_parser = commands.add_parser("broker-discover")
    discover_parser.add_argument("--connect", action="store_true")
    discover_parser.add_argument("--output", type=Path, default=Path(".state/broker-catalog.json"))
    commands.add_parser("broker-logout")
    commands.add_parser("live").add_argument(
        "--state", type=Path, default=Path(".state/live.sqlite3")
    )
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("dataset", type=Path)
    for name in (
        "status",
        "history",
        "propose",
        "quote",
        "approve-execute",
        "cancel",
        "reconcile",
        "halt",
        "resume",
        "backup",
    ):
        command = commands.add_parser(name)
        command.add_argument("--state", type=Path, default=Path(".state/paper.sqlite3"))
        command.add_argument("--policy", type=Path)
        if name in ("propose", "quote", "backup"):
            command.add_argument("file", type=Path)
        if name in ("approve-execute", "cancel", "reconcile", "history"):
            command.add_argument("order_id")
    for name in ("release-manifest", "verify-release"):
        command = commands.add_parser(name)
        command.add_argument("file", type=Path)
        command.add_argument("--policy", type=Path)
        command.add_argument("--root", type=Path, default=Path.cwd())
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            output(
                {
                    "python": sys.version.split()[0],
                    "default_mode": "paper",
                    "default_policy": "deny all orders",
                    "credentials_accessed": False,
                    "live_submission": "disabled: uncertified broker contract",
                }
            )
            return 0
        if args.command == "live":
            raise ExecutionError(
                "Live submission is disabled: broker contracts and account eligibility "
                "are not certified"
            )
        if args.command == "broker-discover":
            if not args.connect or not sys.stdin.isatty():
                raise ExecutionError(
                    "Broker discovery requires --connect in an interactive operator terminal"
                )
            from .connection import discover

            document = asyncio.run(discover())
            args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(document, stream, indent=2)
            output(
                {
                    "catalog": str(args.output),
                    "tools": len(document["tools"]),
                    "catalog_digest": document["catalog_digest"],
                    "tools_enabled": 0,
                }
            )
            return 0
        if args.command == "broker-logout":
            from .connection import KeychainStore

            KeychainStore().clear()
            output({"local_credentials_removed": True, "broker_revocation_required": True})
            return 0
        if args.command == "replay":
            output(replay(args.dataset))
            return 0
        if args.command == "approve-execute" and not sys.stdin.isatty():
            raise ExecutionError("Order approval requires an interactive operator terminal")
        policy = policy_from(args.policy)
        if args.command == "serve":
            from .server import create_server

            create_server(args.state, policy).run(transport="stdio")
            return 0
        if args.command in ("release-manifest", "verify-release"):
            if args.command == "release-manifest":
                manifest = build_manifest(
                    args.root, policy_digest=policy.digest(), capability_digest="unverified"
                )
                args.file.parent.mkdir(parents=True, exist_ok=True)
                with args.file.open("x") as stream:
                    json.dump(manifest, stream, indent=2)
                output({"manifest": str(args.file), "live_certified": False})
            else:
                verify_manifest(
                    args.root, json.loads(args.file.read_text()), policy_digest=policy.digest()
                )
                output({"verified": True, "live_certified": False})
            return 0
        if policy.mode != "paper":
            raise ExecutionError(
                "This operator runtime supports paper execution only; live is disabled"
            )
        state = State(args.state)
        try:
            if args.command == "status":
                output(
                    {
                        "mode": "paper",
                        "halted": state.halted,
                        "orders": [
                            {key: row[key] for key in ("id", "status", "filled_quantity")}
                            for row in state.orders()
                        ],
                    }
                )
                return 0
            if args.command == "backup":
                with state.lock():
                    state.backup(args.file)
                output({"backup": str(args.file)})
                return 0
            if args.command == "history":
                output(
                    {"order": state.get_order(args.order_id), "events": state.events(args.order_id)}
                )
                return 0
            broker = PaperBroker(state, account="paper", cash=Decimal("1000"), fee=Decimal("1"))
            if args.command == "quote":
                broker.set_quote(Quote.model_validate_json(args.file.read_text()))
                output({"quote_loaded": True, "mode": "paper"})
                return 0
            executor = Executor(state, broker, policy, release="development-paper")
            now = datetime.now(UTC)
            if args.command == "propose":
                key = executor.propose(OrderIntent.model_validate_json(args.file.read_text()), now)
                output(executor.review(key, now))
            elif args.command == "approve-execute":
                review = executor.review(args.order_id, now)
                output(review)
                phrase = f"APPROVE {args.order_id} {review['binding'][:12]}"
                if input(f"Type {phrase} to approve this exact PAPER order: ") != phrase:
                    raise ExecutionError("Approval declined")
                now = datetime.now(UTC)
                executor.approve(args.order_id, now, expected_binding=review["binding"])
                output(executor.execute(args.order_id, now).model_dump(mode="json"))
            elif args.command == "cancel":
                output(executor.cancel(args.order_id, now).model_dump(mode="json"))
            elif args.command == "reconcile":
                output(executor.reconcile(args.order_id, now).model_dump(mode="json"))
            elif args.command == "halt":
                executor.halt("operator", now)
                output({"halted": True, "working_orders_canceled": False})
            elif args.command == "resume":
                executor.resume(now)
                output({"halted": False})
            return 0
        finally:
            state.close()
    except (ValueError, ExecutionError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
