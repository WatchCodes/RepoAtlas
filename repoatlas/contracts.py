"""Load contracts from CodeFoundry schemas (single source of truth)."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator

SCHEMA_NAMES = {
    "discovery-manifest": "discovery-manifest.schema.json",
    "migration-request": "migration-request.schema.json",
    "repository-mapping": "repository-mapping.schema.json",
    "migration-report": "migration-report.schema.json",
    "upstream-report": "upstream-report.schema.json",
    "batch-readiness-report": "batch-readiness-report.schema.json",
    "common": "common.definitions.json",
}

def _schemas_dir() -> Path:
    env = os.environ.get("WATCHCODES_SCHEMAS_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent / "CodeFoundry" / "schemas"
    if candidate.is_dir():
        return candidate
    return here.parent / "schemas"

def load_schema(name: str) -> dict[str, Any]:
    return json.loads((_schemas_dir() / SCHEMA_NAMES[name]).read_text(encoding="utf-8"))

def _registry():
    from referencing import Registry, Resource
    registry = Registry()
    for fn in SCHEMA_NAMES.values():
        schema = json.loads((_schemas_dir() / fn).read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema)
        if schema.get("$id"):
            registry = registry.with_resource(schema["$id"], resource)
        registry = registry.with_resource(fn, resource)
    return registry

def validate(name: str, document: Any) -> None:
    Draft202012Validator(load_schema(name), registry=_registry()).validate(document)

def is_valid(name: str, document: Any):
    v = Draft202012Validator(load_schema(name), registry=_registry())
    errs = sorted(v.iter_errors(document), key=lambda e: list(e.path))
    msgs = []
    for e in errs:
        loc = "$" + "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in e.path)
        msgs.append(f"{loc}: {e.message}")
    return (len(errs) == 0, msgs)
