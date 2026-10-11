"""Free diagnostic artifacts; feedback never edits production rules or code."""
def diagnostic_report(snapshot, correction, expected):
    screening = snapshot.get("original_screening") or {}
    result = screening.get("result", {})
    requirements = result.get("requirements", [])
    return {
        "format_version": 1,
        "purpose": "Human-reviewed screening diagnostic for Codex",
        "job": snapshot["job"],
        "original_classification": result.get("classification", "Unscreened"),
        "original_screening": screening,
        "requirements_and_candidate_evidence": requirements,
        "user_correction": correction,
        "expected_classification": expected,
        "proposed_generalizable_improvement": {
            "hypothesis": "Inspect mandatory/preferred extraction, direct industry evidence and unknown-versus-absent handling against the user's correction.",
            "rules_to_review": [
                "A matching title or location must not override mandatory qualification gaps.",
                "Generic implementation/onboarding is not direct fintech, corporate-card or enterprise implementation.",
                "Quote the employer requirement and candidate evidence; keep absent information unknown.",
                "Preferred qualifications and alternative pathways must not become mandatory blockers.",
            ],
            "review_required": True,
            "code_changed": False,
        },
        "regression_case_draft": {
            "description": snapshot["job"].get("descriptionPlain", ""),
            "requirements": requirements,
            "expected_classification": expected,
            "instructions": "Sanitize company, candidate quotations and posting details before creating a public fixture. Review expected behavior before adding a test.",
        },
        "privacy": "Contains private candidate evidence. Keep locally; sanitize before sharing or committing.",
    }
