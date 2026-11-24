"""Regression tests: provenance.origin must be a valid contract enum value.

common.definitions.json permits only hermes|nous|allowlisted. The old code
emitted raw owner.lower(), so every non-hermes owner produced a request that
the sole consumer (CodeFoundry) rejected at schema validation.
"""
from __future__ import annotations

import pytest

from repoatlas.contracts import is_valid
from repoatlas.queue import build_migration_requests


def _manifest(repos: list[str]) -> dict:
    return {
        "schema_version": 1,
        "batch_id": "origin-batch",
        "source": "nastechresearch/hermes-agent",
        "commit_sha": "a" * 40,
        "created_at": "2026-11-22T00:00:00Z",
        "urls": [
            {
                "url": "https://github.com/nastechresearch/hermes-agent",
                "kind": "repository",
                "path": "README.md",
                "line": 1,
                "occurrences": 1,
            }
        ],
        "expected_repositories": repos,
    }


def _assert_schema_valid(requests: list[dict]) -> None:
    assert requests
    for request in requests:
        ok, errors = is_valid("migration-request", request)
        assert ok, errors


@pytest.mark.parametrize(
    ("repo", "expected_origin"),
    [
        ("NousResearch/hermes-agent", "nous"),
        ("Acme/hermes-agent", "hermes"),
        ("Beta/nous-tool", "nous"),
        ("Acme/plain-repo", "allowlisted"),
    ],
)
def test_origin_is_valid_enum_and_matches_lineage(repo: str, expected_origin: str):
    requests = build_migration_requests(_manifest([repo]))

    _assert_schema_valid(requests)
    assert len(requests) == 1
    assert requests[0]["provenance"]["origin"] == expected_origin


@pytest.mark.parametrize(
    "repo",
    [
        "plastic-labs/honcho",
        "BurntSushi/ripgrep",
    ],
)
def test_out_of_scope_roots_are_not_queued(repo: str):
    # README: these roots have no Nastech relationship and must not enter the
    # queue. Fail closed rather than silently labelling them 'allowlisted'.
    assert build_migration_requests(_manifest([repo])) == []


def test_mixed_batch_keeps_in_scope_and_drops_out_of_scope():
    requests = build_migration_requests(
        _manifest(["NousResearch/hermes-agent", "plastic-labs/honcho"])
    )

    _assert_schema_valid(requests)
    assert [r["source"] for r in requests] == ["NousResearch/hermes-agent"]
