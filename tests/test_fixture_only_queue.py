"""Fixture-only URL evidence must never become an approval to create a repo.

README: a test fixture is "excluded unconditionally". The queue previously
ignored ``urls`` entirely, so a schema-valid manifest whose only evidence for
a repo was a fixture URL still emitted a MigrationRequest -- an approval to
create -- for that repo.
"""
from __future__ import annotations

from repoatlas.queue import build_migration_requests

FIXTURE_URL = "https://github.com/O/R/blob/main/tests/fixtures/sample.json"
ROOT_URL = "https://github.com/O/R"


def _manifest(urls: list[dict], expected_repositories: list[str]) -> dict:
    return {
        "schema_version": 1,
        "batch_id": "batch-fixture-001",
        "source": "nastechresearch/hermes-agent",
        "commit_sha": "a" * 40,
        "created_at": "2026-01-01T00:00:00Z",
        "urls": urls,
        "expected_repositories": expected_repositories,
    }


def _url(url: str, kind: str) -> dict:
    return {"url": url, "kind": kind, "path": "README.md", "line": 1, "occurrences": 1}


def test_fixture_only_manifest_does_not_queue_repo():
    manifest = _manifest([_url(FIXTURE_URL, "fixture")], ["O/R"])

    assert build_migration_requests(manifest) == []


def test_real_repo_evidence_overrides_fixture_evidence():
    manifest = _manifest(
        [_url(FIXTURE_URL, "fixture"), _url(ROOT_URL, "repository")], ["O/R"]
    )

    requests = build_migration_requests(manifest)

    assert [req["source"] for req in requests] == ["O/R"]


def test_repo_without_url_evidence_is_still_queued():
    # URL evidence for another repository must not suppress an expected repo
    # that the manifest declares but does not mention in `urls`.
    manifest = _manifest(
        [_url("https://github.com/O/Other", "repository")], ["O/R", "O/Other"]
    )

    requests = build_migration_requests(manifest)

    assert {req["source"] for req in requests} == {"O/R", "O/Other"}
