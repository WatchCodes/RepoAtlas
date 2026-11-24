import json
import subprocess
import sys
from pathlib import Path

import pytest

from repoatlas import contracts
from repoatlas.cli import main


def _valid_manifest():
    return {
        "schema_version": 1,
        "batch_id": "b1",
        "source": "nastechresearch/hermes-agent",
        "commit_sha": "a" * 40,
        "created_at": "2026-01-01T00:00:00Z",
        "urls": [
            {
                "url": "https://github.com/NousResearch/hermes-agent",
                "kind": "repository",
                "path": "README.md",
                "line": 1,
                "occurrences": 1,
            }
        ],
        "expected_repositories": ["NousResearch/hermes-agent"],
    }


def _valid_migration_request():
    return {
        "schema_version": 1,
        "batch_id": "b1",
        "source": "NousResearch/hermes-agent",
        "destination_owner": "WatchCodes",
        "target_name": "nastech-agent",
        "sha": "b" * 40,
        "license": "MIT",
        "action": "create",
        "provenance": {
            "origin": "hermes",
            "discovered_in": "nastechresearch/hermes-agent",
        },
    }


def test_known_schema_names_include_contracts():
    names = contracts.known_schema_names()
    for expected in [
        "discovery-manifest",
        "migration-request",
        "repository-mapping",
        "migration-report",
        "upstream-report",
        "batch-readiness-report",
        "common",
    ]:
        assert expected in names


def test_default_schemas_dir_resolves_codefoundry():
    d = contracts._schemas_dir()
    assert d.name == "schemas"
    assert (d / "discovery-manifest.schema.json").is_file()


def test_unknown_schema_fails_closed():
    with pytest.raises(contracts.ContractError):
        contracts.load_schema("not-a-schema")
    with pytest.raises(contracts.ContractError):
        contracts.validate("not-a-schema", {})
    with pytest.raises(contracts.ContractError):
        contracts.is_valid("not-a-schema", {})


def test_missing_env_schemas_dir_fails_closed(monkeypatch, tmp_path):
    missing = tmp_path / "nope"
    monkeypatch.setenv("WATCHCODES_SCHEMAS_DIR", str(missing))
    contracts._REGISTRY_CACHE.clear()
    with pytest.raises(contracts.ContractError):
        contracts.load_schema("discovery-manifest")
    contracts._REGISTRY_CACHE.clear()


def test_validate_accepts_valid_manifest():
    contracts.validate("discovery-manifest", _valid_manifest())


def test_validate_rejects_invalid_manifest():
    bad = _valid_manifest()
    bad.pop("batch_id")
    ok, errors = contracts.is_valid("discovery-manifest", bad)
    assert ok is False
    assert any("batch_id" in e for e in errors)
    with pytest.raises(Exception):
        contracts.validate("discovery-manifest", bad)


def test_validate_file_and_load_json_file(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
    ok, errors = contracts.validate_file("discovery-manifest", p)
    assert ok is True
    assert errors == []

    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(contracts.ContractError):
        contracts.load_json_file(bad)

    missing = tmp_path / "missing.json"
    with pytest.raises(contracts.ContractError):
        contracts.load_json_file(missing)


def test_migration_request_validation():
    ok, errors = contracts.is_valid("migration-request", _valid_migration_request())
    assert ok is True, errors
    bad = _valid_migration_request()
    bad["action"] = "import_subtree"  # missing subtree_path
    ok, errors = contracts.is_valid("migration-request", bad)
    assert ok is False


def test_cli_validate_success(tmp_path, capsys):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
    rc = main(["validate", "--schema", "discovery-manifest", "--file", str(p)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True


def test_cli_validate_failure(tmp_path, capsys):
    p = tmp_path / "manifest.json"
    bad = _valid_manifest()
    del bad["source"]
    p.write_text(json.dumps(bad), encoding="utf-8")
    rc = main(["validate", "--schema", "discovery-manifest", "--file", str(p)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["ok"] is False
    assert out["errors"]


def test_cli_queue(tmp_path, capsys):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
    rc = main(["queue", "--manifest", str(p), "--destination-owner", "WatchCodes"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["target_name"] == "nastech-agent"
    assert out[0]["action"] == "create"


def test_cli_rename(capsys):
    rc = main(["rename", "my-hermes-plugin", "--owner", "acme"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["target"] == "my-nastech-plugin"
    assert out["status"] == "OK"


def test_cli_invalid_schema_rejected():
    with pytest.raises(SystemExit) as e:
        main(["validate", "--schema", "nope", "--file", "x.json"])
    assert e.value.code == 2


def test_cli_missing_file_fails_closed(capsys):
    rc = main(["queue", "--manifest", "/tmp/does-not-exist-repoatlas.json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["ok"] is False


def _report_with_checkpoints(checkpoints):
    return {
        "schema_version": 1,
        "batch_id": "b1",
        "source": "Owner/Repo",
        "destination": "WatchCodes/nastech-repo",
        "status": "REQUIRES_REVIEW",
        "checks": {
            "created": False, "named": True, "owned": True,
            "gated": True, "license_kept": True, "credits": True,
        },
        "receipt": {
            "idempotency_key": "b1::Owner/Repo",
            "destination_repo_id": 1,
            "source_sha": "a" * 40,
            "destination_sha": "b" * 40,
            "checkpoints": checkpoints,
        },
        "license": {"detected": "MIT", "preserved": True},
        "attribution": {"notice": True, "credits": True},
        "error": "checks not satisfied: created",
    }


def test_migration_report_accepts_every_codefoundry_checkpoint_stage():
    stages = (
        "start", "validate", "receipt", "scan", "license", "clone",
        "brand", "credits", "gate", "ship", "report",
    )
    checkpoints = [{"stage": s, "at": "2026-11-24T00:00:00Z", "ok": True} for s in stages]
    ok, errors = contracts.is_valid("migration-report", _report_with_checkpoints(checkpoints))
    assert ok, errors


def test_migration_report_still_rejects_unknown_checkpoint_stage():
    checkpoints = [{"stage": "not_a_real_stage", "at": "2026-11-24T00:00:00Z", "ok": True}]
    ok, errors = contracts.is_valid("migration-report", _report_with_checkpoints(checkpoints))
    assert ok is False
    assert any("not_a_real_stage" in e for e in errors)
