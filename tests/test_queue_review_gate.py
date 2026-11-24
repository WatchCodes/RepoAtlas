"""A rename result that requires review must never become an approved create request.

The rename engine already refuses reserved and unusable names with
status=REQUIRES_REVIEW. The queue must honour that decision instead of silently
emitting an action=create request for a destination the engine refused.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from repoatlas.cli import main
from repoatlas.queue import QueueValidationError, build_migration_requests


def _manifest(repos: list[str]) -> dict:
    return {
        "schema_version": 1,
        "batch_id": "review-gate-batch",
        "source": "nastechresearch/hermes-agent",
        "commit_sha": "a" * 40,
        "created_at": "2026-11-24T00:00:00Z",
        "urls": [
            {
                "url": "https://github.com/Acme/CON",
                "kind": "repository",
                "path": "README.md",
                "line": 1,
                "occurrences": 1,
            }
        ],
        "expected_repositories": repos,
    }


@pytest.mark.parametrize("repo", ["Acme/CON", "Acme/CON.txt", "Acme/.github"])
def test_reserved_name_cannot_become_create_request(repo: str):
    with pytest.raises(QueueValidationError) as exc:
        build_migration_requests(_manifest([repo]))

    message = str(exc.value).lower()
    assert "review" in message
    assert repo in str(exc.value)


@pytest.mark.parametrize("repo", ["Acme/CON", "Acme/CON.txt", "Acme/.github"])
def test_queue_cli_fails_closed_on_reserved_name(tmp_path: Path, repo: str, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest([repo])), encoding="utf-8")

    code = main(["queue", "--manifest", str(manifest_path)])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "review" in payload["error"].lower()


def test_clean_manifest_still_queues_valid_request():
    requests = build_migration_requests(_manifest(["NousResearch/hermes-agent"]))

    assert len(requests) == 1
    assert requests[0]["action"] == "create"
    assert requests[0]["source"] == "NousResearch/hermes-agent"


def test_queue_module_entrypoint_fails_closed(tmp_path: Path):
    """The installed console entrypoint must obey the same gate."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(["Acme/CON"])), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "repoatlas.cli", "queue", "--manifest", str(manifest_path)],
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "review" in result.stdout.lower()
