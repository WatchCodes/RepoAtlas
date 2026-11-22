"""Hardening tests for URL classification.

These tests lock in deterministic, fail-closed classification behavior and additive
confidence/reasons fields.
"""

from __future__ import annotations

import pytest

from repoatlas.classify import (
    KIND_API_FRAGMENT,
    KIND_API_REPO_FRAGMENT,
    KIND_DEEP_LINK,
    KIND_INVALID,
    KIND_NON_GITHUB,
    KIND_PROFILE,
    KIND_REPO_ROOT,
    KIND_TEST_FIXTURE,
    KNOWN_KINDS,
    classify_url,
)


REQUIRED_FIELDS = {"kind", "repository", "reason", "reasons", "confidence"}


def assert_contract(result: dict) -> None:
    assert REQUIRED_FIELDS.issubset(result.keys())
    assert result["kind"] in KNOWN_KINDS
    assert isinstance(result["reasons"], list)
    assert all(isinstance(r, str) and r for r in result["reasons"])
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0
    if result["repository"] is not None:
        assert isinstance(result["repository"], str)
        assert "/" in result["repository"]
    if result["reason"] is not None:
        assert isinstance(result["reason"], str)
        assert result["reason"]


@pytest.mark.parametrize(
    "url,expected_kind,expected_repo",
    [
        ("https://github.com/NousResearch/hermes-agent", KIND_REPO_ROOT, "NousResearch/hermes-agent"),
        ("https://github.com/NousResearch/hermes-agent.git", KIND_REPO_ROOT, "NousResearch/hermes-agent"),
        ("https://www.github.com/Owner/Repo/", KIND_REPO_ROOT, "Owner/Repo"),
        ("https://github.com/NousResearch/hermes-agent/issues/1", KIND_DEEP_LINK, "NousResearch/hermes-agent"),
        ("https://github.com/NousResearch/hermes-agent/pull/12", KIND_DEEP_LINK, "NousResearch/hermes-agent"),
        ("https://github.com/NousResearch/hermes-agent/blob/main/README.md", KIND_DEEP_LINK, "NousResearch/hermes-agent"),
        ("https://github.com/NousResearch/hermes-agent/tree/main/docs", KIND_DEEP_LINK, "NousResearch/hermes-agent"),
        ("https://github.com/NousResearch/hermes-agent/releases/tag/v1", KIND_DEEP_LINK, "NousResearch/hermes-agent"),
        ("https://api.github.com/repos/NousResearch/hermes-agent", KIND_API_REPO_FRAGMENT, "NousResearch/hermes-agent"),
        ("https://api.github.com/repos/NousResearch/hermes-agent.git", KIND_API_REPO_FRAGMENT, "NousResearch/hermes-agent"),
        ("https://api.github.com/search/repositories?q=hermes", KIND_API_FRAGMENT, None),
        ("https://github.com/NousResearch", KIND_PROFILE, None),
        ("https://example.com/NousResearch/hermes-agent", KIND_NON_GITHUB, None),
    ],
)
def test_category_classification(url: str, expected_kind: str, expected_repo: str | None) -> None:
    result = classify_url(url)
    assert_contract(result)
    assert result["kind"] == expected_kind
    assert result["repository"] == expected_repo


def test_deep_link_extended_repo_paths() -> None:
    # Common repo subpaths should resolve to deep_link, not fail open.
    urls = [
        "https://github.com/O/R/wiki",
        "https://github.com/O/R/actions",
        "https://github.com/O/R/projects/1",
        "https://github.com/O/R/discussions/2",
        "https://github.com/O/R/commits/main",
        "https://github.com/O/R/tags",
        "https://github.com/O/R/branches",
    ]
    for url in urls:
        result = classify_url(url)
        assert_contract(result)
        assert result["kind"] == KIND_DEEP_LINK
        assert result["repository"] == "O/R"


def test_test_fixture_is_excluded_category() -> None:
    result = classify_url("https://github.com/O/R/blob/main/tests/fixtures/sample.json")
    assert_contract(result)
    assert result["kind"] == KIND_TEST_FIXTURE
    assert result["repository"] == "O/R"
    assert result["confidence"] >= 0.9
    assert "test-fixture-path" in result["reasons"]


@pytest.mark.parametrize(
    "url,reason",
    [
        ("", "empty-url"),
        ("   ", "empty-url"),
        ("ftp://github.com/owner/repo", "unsupported-scheme"),
        ("github.com/owner/repo", "unsupported-scheme"),
        ("https:///owner/repo", "missing-host"),
    ],
)
def test_fail_closed_invalid_inputs(url: str, reason: str) -> None:
    result = classify_url(url)
    assert_contract(result)
    assert result["kind"] == KIND_INVALID
    assert result["repository"] is None
    assert result["confidence"] == 0.0
    assert reason in result["reasons"]


@pytest.mark.parametrize("bad", [None, 123, ["https://github.com/o/r"], {"url": "x"}])
def test_fail_closed_non_string_input(bad: object) -> None:
    result = classify_url(bad)  # type: ignore[arg-type]
    assert_contract(result)
    assert result["kind"] == KIND_INVALID
    assert result["repository"] is None
    assert result["confidence"] == 0.0
    assert "invalid-input-type" in result["reasons"]


def test_unrecognized_github_path_fails_closed() -> None:
    result = classify_url("https://github.com/owner/repo/something/unknown")
    assert_contract(result)
    assert result["kind"] == KIND_INVALID
    assert result["repository"] is None
    assert result["confidence"] <= 0.2
    assert "unrecognized" in result["reasons"]


def test_deterministic_output() -> None:
    cases = [
        "https://github.com/NousResearch/hermes-agent",
        "https://github.com/NousResearch/hermes-agent/issues/1",
        "https://github.com/NousResearch",
        "https://api.github.com/search/repositories?q=hermes",
        "https://example.com/foo/bar",
        "not-a-url",
        "",
    ]
    for url in cases:
        first = classify_url(url)
        second = classify_url(url)
        assert first == second
        assert list(first.keys()) == list(second.keys())


def test_confidence_and_reasons_present_for_all_known_kinds() -> None:
    samples = [
        "https://github.com/O/R",
        "https://github.com/O/R/issues/1",
        "https://github.com/O/R/blob/main/tests/fixtures/f.txt",
        "https://github.com/O",
        "https://api.github.com/repos/O/R",
        "https://api.github.com/users/O",
        "https://gitlab.com/O/R",
        "https://github.com/O/R/unknown/path",
    ]
    for url in samples:
        result = classify_url(url)
        assert_contract(result)
        assert "confidence" in result
        assert "reasons" in result
