
"""Consistent rules for final application recommendations."""

from blocker_utils import has_claimed_hard_blockers


def decide_recommendation(
    reviewed_score,
    claimed_blockers,
    strategist_recommendation,
):
    """Apply deterministic safeguards to an AI recommendation."""

    if strategist_recommendation not in {"Apply", "Hold", "Skip"}:
        raise ValueError("Unknown strategist recommendation")

    # Very low scores are not prioritized for applications.
    if reviewed_score < 60:
        return "Skip"

    # Substantive blocker claims require human verification.
    if has_claimed_hard_blockers(claimed_blockers):
        return "Hold"

    # Borderline candidates cannot automatically receive Apply.
    if reviewed_score < 70 and strategist_recommendation == "Apply":
        return "Hold"

    # Otherwise, preserve the strategist's recommendation.
    return strategist_recommendation
