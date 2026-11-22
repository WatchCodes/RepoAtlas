"""RepoAtlas package."""

from .classify import (
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

__all__ = [
    "KIND_API_FRAGMENT",
    "KIND_API_REPO_FRAGMENT",
    "KIND_DEEP_LINK",
    "KIND_INVALID",
    "KIND_NON_GITHUB",
    "KIND_PROFILE",
    "KIND_REPO_ROOT",
    "KIND_TEST_FIXTURE",
    "KNOWN_KINDS",
    "classify_url",
]

__version__ = "0.1.0"
