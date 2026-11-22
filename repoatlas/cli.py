"""Minimal CLI for RepoAtlas contract, queue, and rename flows."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .contracts import ContractError, known_schema_names, validate_file
from .queue import build_migration_requests
from .rename import canonical_target_name


def _emit(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _cmd_validate(args: argparse.Namespace) -> int:
    ok, errors = validate_file(args.schema, args.file)
    if ok:
        _emit({"ok": True, "schema": args.schema, "file": args.file})
        return 0
    _emit({"ok": False, "schema": args.schema, "file": args.file, "errors": errors})
    return 1


def _cmd_queue(args: argparse.Namespace) -> int:
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    requests = build_migration_requests(manifest, destination_owner=args.destination_owner)
    _emit(requests)
    return 0


def _cmd_rename(args: argparse.Namespace) -> int:
    result = canonical_target_name(args.name, owner=args.owner)
    _emit({
        "original": result.original,
        "target": result.target,
        "status": result.status,
        "reason": result.reason,
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repoatlas", description="RepoAtlas contract utilities.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate a JSON document against a contract schema.")
    p_validate.add_argument("--schema", required=True, choices=sorted(known_schema_names()), help="Contract schema name.")
    p_validate.add_argument("--file", required=True, help="Path to JSON document.")
    p_validate.set_defaults(func=_cmd_validate)

    p_queue = sub.add_parser("queue", help="Build MigrationRequest objects from a DiscoveryManifest.")
    p_queue.add_argument("--manifest", required=True, help="Path to DiscoveryManifest JSON file.")
    p_queue.add_argument("--destination-owner", default="WatchCodes", help="Destination owner for generated requests.")
    p_queue.set_defaults(func=_cmd_queue)

    p_rename = sub.add_parser("rename", help="Compute canonical target repository name.")
    p_rename.add_argument("name", help="Source repository name.")
    p_rename.add_argument("--owner", default="", help="Source owner for fallback naming.")
    p_rename.set_defaults(func=_cmd_rename)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ContractError as e:
        _emit({"ok": False, "error": str(e)})
        return 1
    except json.JSONDecodeError as e:
        _emit({"ok": False, "error": f"Invalid JSON: {e}"})
        return 1
    except FileNotFoundError as e:
        _emit({"ok": False, "error": f"File not found: {e}"})
        return 1
    except Exception as e:  # fail closed
        _emit({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
