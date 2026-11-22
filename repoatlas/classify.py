"""URL classification and repository-root resolution.

Classification is deterministic, fail-closed, and returns additive confidence/reasons
fields. Unknown or ambiguous inputs are classified as invalid with low confidence.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Recognized GitHub web hosts.
GITHUB_WEB_HOSTS = frozenset({"github.com", "www.github.com"})
GITHUB_API_HOSTS = frozenset({"api.github.com"})

# Repository root: /owner/repo(.git)?
REPO_ROOT_RE = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")

# Deep links that resolve to a parent repository.
DEEP_LINK_RE = re.compile(
    r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/"
    r"(issues|pull|pulls|releases|tree|blob|commit|commits|compare|wiki|discussions|actions|projects|security|graphs|pulse|settings|packages|tags|branches)"
    r"(/|$)"
)

# API repository fragment: /repos/owner/repo(.git)?
API_REPO_RE = re.compile(r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")

# Conservative fixture markers for file/blob deep links.
FIXTURE_PATH_RE = re.compile(
    r"(^|/)(__fixtures__|fixtures?|test[_-]?fixtures?)(/|$)|"
    r"/tests?/fixtures?(/|$)",
    re.IGNORECASE,
)

# Kinds are clear, stable categories. Additive fields may evolve.
KIND_REPO_ROOT = "repo_root"
KIND_DEEP_LINK = "deep_link"
KIND_PROFILE = "profile"
KIND_API_REPO_FRAGMENT = "api_repo_fragment"
KIND_API_FRAGMENT = "api_fragment"
KIND_TEST_FIXTURE = "test_fixture"
KIND_NON_GITHUB = "non_github"
KIND_INVALID = "invalid"

KNOWN_KINDS = frozenset(
    {
        KIND_REPO_ROOT,
        KIND_DEEP_LINK,
        KIND_PROFILE,
        KIND_API_REPO_FRAGMENT,
        KIND_API_FRAGMENT,
        KIND_TEST_FIXTURE,
        KIND_NON_GITHUB,
        KIND_INVALID,
    }
)


def _result(
    kind: str,
    repository: str | None,
    *,
    confidence: float,
    reasons: list[str],
    reason: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic classification result.

    `reason` is kept for backward compatibility; `reasons` is the canonical additive field.
    """
    if kind not in KNOWN_KINDS:
        kind = KIND_INVALID
    # Clamp and normalize confidence to a deterministic float in [0.0, 1.0].
    conf = float(confidence)
    if conf < 0.0:
        conf = 0.0
    elif conf > 1.0:
        conf = 1.0
    # Deterministic reasons: preserve order, remove empties, stringify.
    norm_reasons: list[str] = []
    for r in reasons:
        if r is None:
            continue
        s = str(r).strip()
        if s:
            norm_reasons.append(s)
    if reason is None and norm_reasons:
        reason = norm_reasons[0]
    if reason is not None:
        reason = str(reason).strip() or None
    return {
        "kind": kind,
        "repository": repository,
        "reason": reason,
        "reasons": norm_reasons,
        "confidence": round(conf, 3),
    }


def _normalize_repository(owner: str, repo: str) -> str | None:
    owner = owner.strip()
    repo = repo.strip()
    # Strip .git suffix defensively; regex usually handles it.
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def _is_test_fixture_path(path: str) -> bool:
    return bool(FIXTURE_PATH_RE.search(path or ""))


def classify_url(url: object) -> dict[str, Any]:
    """Classify a URL into a clear, deterministic category.

    Returns a dict with at least:
    - kind: stable category string
    - repository: "owner/repo" when resolvable, else None
    - reason: primary reason string or None (compat)
    - reasons: list of reason strings (additive, canonical)
    - confidence: deterministic confidence in [0.0, 1.0]

    Unknown, ambiguous, or unsupported inputs fail closed as invalid.
    """
    if not isinstance(url, str):
        return _result(
            KIND_INVALID,
            None,
            confidence=0.0,
            reasons=["invalid-input-type"],
            reason="invalid-input-type",
        )

    raw = url.strip()
    if not raw:
        return _result(
            KIND_INVALID,
            None,
            confidence=0.0,
            reasons=["empty-url"],
            reason="empty-url",
        )

    try:
        parsed = urlparse(raw)
    except Exception:
        return _result(
            KIND_INVALID,
            None,
            confidence=0.0,
            reasons=["parse-error"],
            reason="parse-error",
        )

    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"

    if scheme not in {"http", "https"}:
        return _result(
            KIND_INVALID,
            None,
            confidence=0.0,
            reasons=["unsupported-scheme"],
            reason="unsupported-scheme",
        )

    if not host:
        return _result(
            KIND_INVALID,
            None,
            confidence=0.0,
            reasons=["missing-host"],
            reason="missing-host",
        )

    if host in GITHUB_API_HOSTS:
        m = API_REPO_RE.match(path)
        if m:
            repo = _normalize_repository(m.group("owner"), m.group("repo"))
            if repo is None:
                return _result(
                    KIND_INVALID,
                    None,
                    confidence=0.0,
                    reasons=["invalid-repository-segment"],
                    reason="invalid-repository-segment",
                )
            return _result(
                KIND_API_REPO_FRAGMENT,
                repo,
                confidence=0.99,
                reasons=[],
                reason=None,
            )
        return _result(
            KIND_API_FRAGMENT,
            None,
            confidence=0.95,
            reasons=["not-repo"],
            reason="not-repo",
        )

    if host not in GITHUB_WEB_HOSTS:
        return _result(
            KIND_NON_GITHUB,
            None,
            confidence=0.99,
            reasons=["unsupported-host"],
            reason="unsupported-host",
        )

    m = REPO_ROOT_RE.match(path)
    if m:
        repo = _normalize_repository(m.group("owner"), m.group("repo"))
        if repo is None:
            return _result(
                KIND_INVALID,
                None,
                confidence=0.0,
                reasons=["invalid-repository-segment"],
                reason="invalid-repository-segment",
            )
        return _result(
            KIND_REPO_ROOT,
            repo,
            confidence=1.0,
            reasons=[],
            reason=None,
        )

    m = DEEP_LINK_RE.match(path)
    if m:
        repo = _normalize_repository(m.group("owner"), m.group("repo"))
        if repo is None:
            return _result(
                KIND_INVALID,
                None,
                confidence=0.0,
                reasons=["invalid-repository-segment"],
                reason="invalid-repository-segment",
            )
        if _is_test_fixture_path(path):
            return _result(
                KIND_TEST_FIXTURE,
                repo,
                confidence=0.98,
                reasons=["test-fixture-path"],
                reason="test-fixture-path",
            )
        return _result(
            KIND_DEEP_LINK,
            repo,
            confidence=0.99,
            reasons=[],
            reason=None,
        )

    parts = [x for x in path.split("/") if x]
    if len(parts) == 1:
        return _result(
            KIND_PROFILE,
            None,
            confidence=0.98,
            reasons=["profile-not-repo"],
            reason="profile-not-repo",
        )

    # Unknown GitHub path shape: fail closed. Do not guess repository identity.
    return _result(
        KIND_INVALID,
        None,
        confidence=0.1,
        reasons=["unrecognized"],
        reason="unrecognized",
    )
