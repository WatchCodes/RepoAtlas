"""Canonical rename algorithm (RepoAtlas owns this)."""
from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass
class RenameResult:
    original: str
    target: str
    status: str  # OK | REQUIRES_REVIEW
    reason: str | None = None


def canonical_target_name(name: str, *, owner: str = "") -> RenameResult:
    original = name
    if name == "nastech" or name.startswith("nastech-"):
        target = name
    else:
        # replace hermes/nous case-insensitively
        target = re.sub(r"hermes|nous", "nastech", name, flags=re.IGNORECASE)
        target = re.sub(r"nastech-nastech", "nastech", target, flags=re.IGNORECASE)
    # sanitise to [A-Za-z0-9._-], max 100, no leading dot
    target = re.sub(r"[^A-Za-z0-9._-]", "-", target)
    target = target.lstrip(".")
    target = target[:100]
    if not target:
        fallback_owner = re.sub(r"[^A-Za-z0-9._-]", "-", owner) or "unknown"
        target = f"nastech-{fallback_owner}-{original}"[:100]
    return RenameResult(original=original, target=target, status="OK")


def ext_collision_name(base: str, ext: str) -> str:
    """Convention for extension collisions: nastech-agent-ext-<name>."""
    ext_clean = re.sub(r"[^A-Za-z0-9._-]", "-", ext).strip("-").lower() or "ext"
    return f"{base}-ext-{ext_clean}"[:100]
