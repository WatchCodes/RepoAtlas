"""URL classification and repository-root resolution."""
from __future__ import annotations
import re
from urllib.parse import urlparse

REPO_ROOT_RE = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")
ISSUE_PR_RE = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(issues|pull|releases|tree|blob|commit|compare)(/|$)")
API_REPO_RE = re.compile(r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def classify_url(url: str) -> dict:
    try:
        p = urlparse(url)
    except Exception:
        return {"kind": "invalid", "repository": None, "reason": "parse-error"}
    host = (p.hostname or "").lower()
    path = p.path or "/"
    if host in {"api.github.com"}:
        m = API_REPO_RE.match(path)
        if m:
            return {"kind": "api_repo_fragment", "repository": f"{m.group('owner')}/{m.group('repo')}", "reason": None}
        return {"kind": "api_fragment", "repository": None, "reason": "not-repo"}
    if host not in {"github.com", "www.github.com"}:
        return {"kind": "non_github", "repository": None, "reason": "unsupported-host"}
    m = REPO_ROOT_RE.match(path)
    if m:
        return {"kind": "repo_root", "repository": f"{m.group('owner')}/{m.group('repo')}", "reason": None}
    m = ISSUE_PR_RE.match(path)
    if m:
        return {"kind": "deep_link", "repository": f"{m.group('owner')}/{m.group('repo')}", "reason": None}
    # profile or other
    parts = [x for x in path.split("/") if x]
    if len(parts) == 1:
        return {"kind": "profile", "repository": None, "reason": "profile-not-repo"}
    return {"kind": "invalid", "repository": None, "reason": "unrecognized"}
