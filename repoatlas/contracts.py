"""Load and validate contracts from CodeFoundry schemas (single source of truth)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_NAMES: dict[str, str] = {
    "discovery-manifest": "discovery-manifest.schema.json",
    "migration-request": "migration-request.schema.json",
    "repository-mapping": "repository-mapping.schema.json",
    "migration-report": "migration-report.schema.json",
    "upstream-report": "upstream-report.schema.json",
    "batch-readiness-report": "batch-readiness-report.schema.json",
    "common": "common.definitions.json",
}

_REGISTRY_CACHE: dict[str, Any] = {}


class ContractError(ValueError):
    """Raised when a contract name, schema, or document is invalid."""


def known_schema_names() -> tuple[str, ...]:
    return tuple(SCHEMA_NAMES)


def _resolve_schemas_dir() -> Path:
    env = os.environ.get("WATCHCODES_SCHEMAS_DIR")
    if env:
        p = Path(env).expanduser()
        if not p.is_dir():
            raise ContractError(f"WATCHCODES_SCHEMAS_DIR is not a directory: {p}")
        return p.resolve()

    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent / "CodeFoundry" / "schemas",
        here.parent / "schemas",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    searched = ", ".join(str(c) for c in candidates)
    raise ContractError(f"Schema directory not found; searched: {searched}")


# Backward-compatible name used internally/externally.
def _schemas_dir() -> Path:
    return _resolve_schemas_dir()


def _schema_path(name: str) -> Path:
    if name not in SCHEMA_NAMES:
        known = ", ".join(sorted(SCHEMA_NAMES))
        raise ContractError(f"Unknown schema {name!r}; known schemas: {known}")
    path = _resolve_schemas_dir() / SCHEMA_NAMES[name]
    if not path.is_file():
        raise ContractError(f"Schema file missing for {name!r}: {path}")
    return path


def load_schema(name: str) -> dict[str, Any]:
    path = _schema_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ContractError(f"Schema {name!r} is not valid JSON: {path}: {e}") from e
    if not isinstance(data, dict):
        raise ContractError(f"Schema {name!r} must be a JSON object: {path}")
    return data


def _registry():
    from referencing import Registry, Resource

    schemas_dir = _resolve_schemas_dir()
    cache_key = str(schemas_dir)
    cached = _REGISTRY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    registry = Registry()
    for schema_name, fn in SCHEMA_NAMES.items():
        path = schemas_dir / fn
        if not path.is_file():
            raise ContractError(f"Schema file missing for {schema_name!r}: {path}")
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ContractError(f"Schema {schema_name!r} is not valid JSON: {path}: {e}") from e
        if not isinstance(schema, dict):
            raise ContractError(f"Schema {schema_name!r} must be a JSON object: {path}")
        resource = Resource.from_contents(schema)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
        registry = registry.with_resource(fn, resource)
    _REGISTRY_CACHE[cache_key] = registry
    return registry


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name), registry=_registry())


def validate(name: str, document: Any) -> None:
    """Validate document against named contract; raises on failure."""
    _validator(name).validate(document)


def is_valid(name: str, document: Any) -> tuple[bool, list[str]]:
    """Return (ok, errors) for named contract. Fails closed on unknown schema."""
    errs = sorted(_validator(name).iter_errors(document), key=lambda e: list(e.path))
    msgs: list[str] = []
    for e in errs:
        loc = "$" + "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in e.path)
        msgs.append(f"{loc}: {e.message}")
    return (len(errs) == 0, msgs)


def load_json_file(path: str | Path) -> Any:
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ContractError(f"JSON file not found: {p}") from e
    except json.JSONDecodeError as e:
        raise ContractError(f"Invalid JSON in {p}: {e}") from e


def validate_file(name: str, path: str | Path) -> tuple[bool, list[str]]:
    document = load_json_file(path)
    return is_valid(name, document)
