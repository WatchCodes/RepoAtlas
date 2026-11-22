"""Canonical rename algorithm (RepoAtlas owns this)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]")
_HYPHEN_RUN_RE = re.compile(r"-{2,}")
_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *[f"com{i}" for i in range(1, 10)], *[f"lpt{i}" for i in range(1, 10)]}
)
_RESERVED_NAMES = frozenset({".", "..", ".git", ".github"}) | _RESERVED_DEVICE_NAMES
_MAX_NAME_LEN = 100


@dataclass
class RenameResult:
    original: str
    target: str
    status: str  # OK | REQUIRES_REVIEW
    reason: str | None = None


def _fail_closed(original: object, *, owner: object = "", reason: str) -> RenameResult:
    owner_slug = _sanitize_slug(owner if isinstance(owner, str) else "", allow_empty=True).strip("-_.")
    owner_part = owner_slug.lower() or "unknown"
    fallback = _truncate_safe(f"nastech-{owner_part}-invalid")
    if not fallback:
        fallback = "nastech-invalid"
    return RenameResult(original=str(original) if original is not None else "", target=fallback, status="REQUIRES_REVIEW", reason=reason)


def _sanitize_slug(value: str, *, allow_empty: bool = False) -> str:
    cleaned = _SAFE_CHARS_RE.sub("-", value)
    cleaned = _HYPHEN_RUN_RE.sub("-", cleaned)
    cleaned = cleaned.lstrip(".")
    cleaned = cleaned.rstrip(".")
    cleaned = cleaned[:_MAX_NAME_LEN]
    cleaned = cleaned.rstrip(".")
    if not allow_empty and not cleaned:
        return ""
    return cleaned


def _truncate_safe(value: str) -> str:
    value = value[:_MAX_NAME_LEN]
    value = value.lstrip(".")
    value = value.rstrip(".")
    if len(value) > _MAX_NAME_LEN:
        value = value[:_MAX_NAME_LEN].rstrip(".")
    return value


def _is_reserved_name(name: str) -> bool:
    lowered = name.lower()
    if lowered in _RESERVED_NAMES:
        return True
    # Windows device names are reserved even with an extension.
    base = lowered.split(".", 1)[0]
    return base in _RESERVED_DEVICE_NAMES


def _collapse_nastech_runs(value: str) -> str:
    # Collapse repeated nastech markers deterministically, case-insensitively.
    pattern = re.compile(r"nastech(?:[-_.]?nastech)+", flags=re.IGNORECASE)
    previous = None
    current = value
    while current != previous:
        previous = current
        current = pattern.sub("nastech", current)
    return current


def _apply_nastech_policy(name: str) -> str:
    if name == "nastech" or name.startswith("nastech-"):
        target = name
    else:
        target = re.sub(r"hermes|nous", "nastech", name, flags=re.IGNORECASE)
        target = _collapse_nastech_runs(target)
    return target


def canonical_target_name(name: str, *, owner: str = "") -> RenameResult:
    if not isinstance(name, str) or not isinstance(owner, str):
        return _fail_closed(name, owner=owner, reason="invalid-input-type")
    original = name
    if not name or not name.strip():
        return _fail_closed(original, owner=owner, reason="empty-name")

    raw_target = _apply_nastech_policy(name)
    raw_stripped = raw_target.strip()
    if _is_reserved_name(raw_stripped) or _is_reserved_name(raw_stripped.lstrip(".")):
        fallback_owner = _sanitize_slug(owner, allow_empty=True).strip("-_.") or "unknown"
        safe_raw = _sanitize_slug(raw_stripped, allow_empty=True).strip("-_.") or "reserved"
        target = _truncate_safe(f"nastech-{fallback_owner}-{safe_raw}")
        if not target or _is_reserved_name(target):
            target = "nastech-reserved-name"
        return RenameResult(original=original, target=target, status="REQUIRES_REVIEW", reason="reserved-name")

    target = _sanitize_slug(raw_target)

    if not target:
        fallback_owner = _sanitize_slug(owner, allow_empty=True).strip("-_.") or "unknown"
        raw_original = _sanitize_slug(original, allow_empty=True).strip("-_.") or "unnamed"
        target = _truncate_safe(f"nastech-{fallback_owner}-{raw_original}")
        if not target:
            target = "nastech-unknown-unnamed"
        return RenameResult(original=original, target=target, status="OK", reason="fallback-empty-slug")

    if _is_reserved_name(target):
        fallback_owner = _sanitize_slug(owner, allow_empty=True).strip("-_.") or "unknown"
        safe_target = _sanitize_slug(target, allow_empty=True).strip("-_.") or "reserved"
        target = _truncate_safe(f"nastech-{fallback_owner}-{safe_target}")
        if not target or _is_reserved_name(target):
            target = "nastech-reserved-name"
        return RenameResult(original=original, target=target, status="REQUIRES_REVIEW", reason="reserved-name")

    if len(target) > _MAX_NAME_LEN:
        target = _truncate_safe(target)

    if not target:
        return _fail_closed(original, owner=owner, reason="empty-after-sanitize")

    return RenameResult(original=original, target=target, status="OK")


def ext_collision_name(base: str, ext: str) -> str:
    """Deterministic collision suffix: <base>-ext-<ext>."""
    if not isinstance(base, str) or not isinstance(ext, str):
        raise TypeError("base and ext must be strings")
    base_clean = _sanitize_slug(base, allow_empty=True).strip("-_.")
    ext_clean = _sanitize_slug(ext, allow_empty=True).strip("-_.").lower()
    if not base_clean:
        base_clean = "nastech-collision"
    if not ext_clean:
        ext_clean = "ext"
    suffix = f"-ext-{ext_clean}"
    max_base = _MAX_NAME_LEN - len(suffix)
    if max_base < 1:
        # Extremely long extension; keep deterministic, bounded output.
        ext_clean = ext_clean[: max(1, _MAX_NAME_LEN - len("-ext-") - 1)]
        suffix = f"-ext-{ext_clean}"
        max_base = _MAX_NAME_LEN - len(suffix)
    base_trimmed = base_clean[:max_base].rstrip("-_.")
    if not base_trimmed:
        base_trimmed = "nastech-collision"[:max_base].rstrip("-_.") or "n"
    candidate = f"{base_trimmed}{suffix}"
    candidate = _truncate_safe(candidate)
    if not candidate:
        return "nastech-collision-ext"
    return candidate

