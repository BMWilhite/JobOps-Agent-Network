
"""Shared utilities for reviewing AI-claimed hard blockers."""

NO_BLOCKER_PHRASES = {
    "",
    "none",
    "none found",
    "none identified",
    "no blockers",
    "no hard blockers",
    "no confirmed hard blockers",
    "n/a",
    "none found; all mandatory qualifications have some reasonable evidence or transferability",
}


def has_claimed_hard_blockers(blockers):
    """Return True only when a substantive blocker claim exists."""

    return any(
        str(item).strip().casefold().rstrip(".!")
        not in NO_BLOCKER_PHRASES
        for item in (blockers or [])
    )
