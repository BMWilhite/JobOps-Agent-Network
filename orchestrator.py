
import json
from pathlib import Path

from agents import Runner

from save_evaluation import save_evaluation

from extraction_agent import extraction_agent, sample_job
from fit_analyst import fit_analyst
from skeptical_reviewer import skeptical_reviewer
from application_strategist import application_strategist


SCORE_LIMITS = {
    "hard_requirements": 30,
    "work_shape": 25,
    "relevant_experience": 15,
    "compensation": 10,
    "geography": 10,
    "mission_and_trajectory": 10,
}


def calculate_score(scores):
    """Validate category scores and calculate the total."""

    total = 0

    for category, maximum in SCORE_LIMITS.items():
        value = getattr(scores, category)

        if not 0 <= value <= maximum:
            raise ValueError(
                f"Invalid score for {category}: {value}"
            )

        total += value

    return total


def evaluate_job(raw_posting, profile_path=None):
    """Run the complete four-agent evaluation workflow."""

    if profile_path is None:
        profile_path = Path(__file__).with_name(
            "candidate_profile.md"
        )

    profile = Path(profile_path).read_text(
        encoding="utf-8"
    )


    print("1/4 Extracting job...")
    job = Runner.run_sync(
        extraction_agent,
        raw_posting,
    ).final_output

    print("2/4 Analyzing candidate fit...")
    assessment = Runner.run_sync(
        fit_analyst,
        json.dumps({
            "candidate_profile": profile,
            "job": job.model_dump(),
        }),
    ).final_output

    initial_score = calculate_score(assessment.scores)

    print("3/4 Running independent review...")
    review = Runner.run_sync(
        skeptical_reviewer,
        json.dumps({
            "candidate_profile": profile,
            "job": job.model_dump(),
            "initial_assessment": assessment.model_dump(),
        }),
    ).final_output

    reviewed_score = calculate_score(review.revised_scores)

    print("4/4 Developing application strategy...")
    plan = Runner.run_sync(
        application_strategist,
        json.dumps({
            "candidate_profile": profile,
            "job": job.model_dump(),
            "initial_assessment": assessment.model_dump(),
            "skeptical_review": review.model_dump(),
            "reviewed_score": reviewed_score,
        }),
    ).final_output

  
    # AI-identified blockers require verification.
    blocker_review_required = bool(
        review.confirmed_hard_blockers
    )

    if reviewed_score < 60:
        decision = "Skip"

    elif blocker_review_required:
        decision = "Hold"

    elif reviewed_score < 70 and plan.recommendation == "Apply":
        decision = "Hold"

    else:
        decision = plan.recommendation


    return {
        "job": job.model_dump(),
        "initial_assessment": assessment.model_dump(),
        "review": review.model_dump(),
        "strategy": plan.model_dump(),
        "initial_score": initial_score,
        "reviewed_score": reviewed_score,
        "recommendation": decision,
    }



if __name__ == "__main__":

    # Read the real job posting.
    posting_path = Path(__file__).with_name(
        "job_posting.txt"
    )

    raw_posting = posting_path.read_text(
        encoding="utf-8"
    )

    if not raw_posting.strip():
        raise ValueError("Job posting file is empty.")

    print("Starting JobOps evaluation...\n")

    # Run the complete four-agent workflow.
    result = evaluate_job(raw_posting)

    # Preserve the original posting for SQLite.
    result["raw_posting"] = raw_posting

    # Save the complete evaluation as JSON.
    output_path = Path(__file__).with_name(
        "latest_evaluation.json"
    )

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Automatically store the evaluation in SQLite.
    save_evaluation()

    # Display a concise summary.
    job = result["job"]

    print("\n===== JOBOPS EVALUATION =====")
    print(f"Company: {job['company']}")
    print(f"Title: {job['title']}")
    print(f"Initial fit: {result['initial_score']}/100")
    print(f"Reviewed fit: {result['reviewed_score']}/100")
    print(f"Decision: {result['recommendation']}")

    print("\nRecommendation reasoning:")
    print(result["strategy"]["recommendation_reason"])

    print("\nReviewer challenges:")
    for concern in result["review"]["disputed_claims"]:
        print(f"- {concern}")

    print("\nEvaluation saved to:")
    print(output_path)
