"""Hardening tests for rename policy and queue/idempotency/collision behavior."""
from __future__ import annotations

import re

import pytest

from jsonschema import ValidationError

from repoatlas.queue import QueueValidationError, build_migration_requests
from repoatlas.rename import RenameResult, canonical_target_name, ext_collision_name


def _manifest(
    *,
    batch_id: str = "batch-hardening-001",
    source: str = "nastechresearch/hermes-agent",
    commit_sha: str = "a" * 40,
    created_at: str = "2026-01-01T00:00:00Z",
    urls: list[dict] | None = None,
    expected_repositories: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "source": source,
        "commit_sha": commit_sha,
        "created_at": created_at,
        "urls": urls
        or [
            {
                "url": "https://github.com/NousResearch/hermes-agent",
                "kind": "repository",
                "path": "README.md",
                "line": 1,
                "occurrences": 1,
            }
        ],
        "expected_repositories": (
            ["NousResearch/hermes-agent"] if expected_repositories is None else expected_repositories
        ),
    }


# --- rename: deterministic and safe slugs ---


def test_rename_is_deterministic():
    inputs = [
        ("hermes-agent", "NousResearch"),
        ("my-nous-plugin", "Acme"),
        ("nastech-agent", ""),
    ]
    for name, owner in inputs:
        a = canonical_target_name(name, owner=owner)
        b = canonical_target_name(name, owner=owner)
        assert (a.original, a.target, a.status, a.reason) == (
            b.original,
            b.target,
            b.status,
            b.reason,
        )


def test_rename_sanitizes_unsafe_chars_and_trims_dots():
    r = canonical_target_name("..hermes agent!@#$%", owner="Acme")
    assert r.status == "OK"
    assert r.target
    assert not r.target.startswith(".")
    assert all(c.isalnum() or c in "._-" for c in r.target)
    assert " " not in r.target
    assert "!" not in r.target


def test_rename_enforces_max_length():
    long_name = "hermes-" + ("a" * 200)
    r = canonical_target_name(long_name, owner="owner")
    assert r.status == "OK"
    assert len(r.target) <= 100
    assert r.target


def test_rename_collapses_nastech_runs_case_insensitively():
    r = canonical_target_name("hermes-nous-hermes-tool", owner="Acme")
    assert r.status == "OK"
    assert "nastech-nastech" not in r.target.lower()
    assert r.target == "nastech-tool"


def test_rename_preserves_nastech_prefixed_name():
    r = canonical_target_name("nastech-already-good", owner="Acme")
    assert r.status == "OK"
    assert r.target == "nastech-already-good"


# --- rename: reserved names ---


@pytest.mark.parametrize(
    "reserved",
    [
        "CON",
        "con",
        "prn",
        "aux",
        "nul",
        "com1",
        "COM9",
        "lpt1",
        "LPT9",
        ".git",
        ".github",
    ],
)
def test_rename_reserved_names_fail_closed(reserved):
    r = canonical_target_name(reserved, owner="Acme")
    assert r.status == "REQUIRES_REVIEW"
    assert r.reason == "reserved-name"
    assert r.target
    assert len(r.target) <= 100
    assert all(c.isalnum() or c in "._-" for c in r.target)


def test_rename_reserved_device_name_with_extension_fails_closed():
    r = canonical_target_name("CON.txt", owner="Acme")
    assert r.status == "REQUIRES_REVIEW"
    assert r.reason == "reserved-name"


# --- rename: fail-closed invalid input ---


@pytest.mark.parametrize("bad_name", [None, 123, [], {}, 3.14])
def test_rename_invalid_input_type_fails_closed(bad_name):
    r = canonical_target_name(bad_name, owner="Acme")  # type: ignore[arg-type]
    assert r.status == "REQUIRES_REVIEW"
    assert r.reason == "invalid-input-type"
    assert r.target
    assert len(r.target) <= 100


@pytest.mark.parametrize("bad_name", ["", "   ", "\n\t"])
def test_rename_empty_name_fails_closed(bad_name):
    r = canonical_target_name(bad_name, owner="Acme")
    assert r.status == "REQUIRES_REVIEW"
    assert r.reason == "empty-name"
    assert r.target
    assert len(r.target) <= 100


def test_rename_invalid_owner_type_fails_closed():
    r = canonical_target_name("hermes-agent", owner=None)  # type: ignore[arg-type]
    assert r.status == "REQUIRES_REVIEW"
    assert r.reason == "invalid-input-type"


def test_rename_fallback_when_sanitized_empty():
    r = canonical_target_name("...", owner="Acme")
    # Either fallback to a safe name or fail closed; must not return empty target.
    assert r.target
    assert len(r.target) <= 100
    assert all(c.isalnum() or c in "._-" for c in r.target)
    assert r.status in {"OK", "REQUIRES_REVIEW"}


# --- rename: collision helper ---


def test_ext_collision_name_is_deterministic_and_safe():
    a = ext_collision_name("nastech-agent", "Acme/Repo")
    b = ext_collision_name("nastech-agent", "Acme/Repo")
    assert a == b
    assert a.startswith("nastech-agent-ext-")
    assert len(a) <= 100
    assert all(c.isalnum() or c in "._-" for c in a)
    assert "-2" not in a.split("-ext-")[-1]


def test_ext_collision_name_rejects_bad_types():
    with pytest.raises(TypeError):
        ext_collision_name(None, "x")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ext_collision_name("base", None)  # type: ignore[arg-type]


def test_ext_collision_name_bounds_long_input():
    base = "nastech-" + ("b" * 150)
    ext = "owner-" + ("e" * 150)
    result = ext_collision_name(base, ext)
    assert len(result) <= 100
    assert result
    assert "-ext-" in result


# --- queue: fail-closed invalid input ---


def test_queue_rejects_non_dict_manifest():
    with pytest.raises(QueueValidationError):
        build_migration_requests([])  # type: ignore[arg-type]


def test_queue_rejects_invalid_destination_owner():
    manifest = _manifest()
    with pytest.raises(QueueValidationError):
        build_migration_requests(manifest, destination_owner="bad owner")
    with pytest.raises(QueueValidationError):
        build_migration_requests(manifest, destination_owner="")


def test_queue_rejects_invalid_repo_refs_fail_closed():
    manifest = _manifest(expected_repositories=["not-a-repo-ref"])
    with pytest.raises(QueueValidationError):
        build_migration_requests(manifest)

    manifest2 = _manifest(expected_repositories=["owner/"])
    with pytest.raises(QueueValidationError):
        build_migration_requests(manifest2)

    manifest3 = _manifest(expected_repositories=["/name"])
    with pytest.raises(QueueValidationError):
        build_migration_requests(manifest3)


def test_queue_rejects_non_string_repo_refs():
    manifest = _manifest(expected_repositories=[{"owner": "x"}])  # type: ignore[list-item]
    with pytest.raises((QueueValidationError, ValidationError)):
        build_migration_requests(manifest)


# --- queue: idempotency and deterministic ordering ---


def test_queue_is_idempotent_for_same_manifest():
    manifest = _manifest(
        batch_id="batch-idem-hardening",
        expected_repositories=[
            "Zeta/hermes-tool",
            "Acme/nous-lib",
            "Zeta/hermes-tool",
        ],
    )
    first = build_migration_requests(manifest, destination_owner="WatchCodes")
    second = build_migration_requests(manifest, destination_owner="WatchCodes")
    assert first == second


def test_queue_orders_and_dedupes_case_insensitively():
    manifest = _manifest(
        expected_repositories=[
            "zeta/hermes-tool",
            "Acme/nous-lib",
            "ZETA/hermes-tool",
            "acme/nous-lib",
        ]
    )
    reqs = build_migration_requests(manifest)
    sources = [r["source"] for r in reqs]
    assert len(sources) == 2
    assert sources == sorted(sources, key=str.lower)
    # deterministic representative: first seen in input order per lower-key
    assert sources[0].lower() == "acme/nous-lib"
    assert sources[1].lower() == "zeta/hermes-tool"


# --- queue: collision naming ---


def test_queue_collision_naming_is_deterministic_and_unique():
    manifest = _manifest(
        batch_id="batch-collision-hardening",
        expected_repositories=[
            "Alice/hermes-tool",
            "Bob/hermes-tool",
            "Cara/hermes-tool",
        ],
    )
    reqs_a = build_migration_requests(manifest)
    reqs_b = build_migration_requests(manifest)
    assert reqs_a == reqs_b
    targets = [r["target_name"] for r in reqs_a]
    assert len(targets) == 3
    assert len({t.lower() for t in targets}) == 3
    assert targets[0] == "nastech-tool"
    for t in targets[1:]:
        assert "-ext-" in t
        assert not t.endswith("-2")
        assert len(t) <= 100
        assert all(c.isalnum() or c in "._-" for c in t)


def test_queue_collision_naming_never_appends_dash_two():
    manifest = _manifest(
        expected_repositories=[
            "A/hermes-lib",
            "B/hermes-lib",
            "C/hermes-lib",
            "D/hermes-lib",
        ]
    )
    reqs = build_migration_requests(manifest)
    targets = [r["target_name"] for r in reqs]
    assert len(set(t.lower() for t in targets)) == len(targets)
    for t in targets:
        assert not re.search(r"-2(?:$|[^0-9])", t)


def test_queue_requests_have_required_shape():
    manifest = _manifest(
        expected_repositories=["Acme/hermes-agent", "Beta/nous-tool"],
    )
    reqs = build_migration_requests(manifest, destination_owner="WatchCodes")
    assert len(reqs) == 2
    for req in reqs:
        assert req["schema_version"] == 1
        assert req["batch_id"] == "batch-hardening-001"
        assert req["destination_owner"] == "WatchCodes"
        assert req["sha"] == "a" * 40
        assert req["action"] == "create"
        assert req["license"] == "NOASSERTION"
        assert "provenance" in req
        assert req["provenance"]["discovered_in"] == "nastechresearch/hermes-agent"
        assert req["provenance"]["manifest_batch_id"] == "batch-hardening-001"
        assert len(req["target_name"]) <= 100

