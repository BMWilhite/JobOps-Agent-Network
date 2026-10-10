
from job_discovery import (
    fetch_ashby_jobs,
    format_job_for_evaluation,
)
from orchestrator import evaluate_job
from database import initialize_database
from save_evaluation import save_evaluation


if __name__ == "__main__":
    print("Retrieving Stedi's job posting...")

    jobs = fetch_ashby_jobs("stedi")

    job = next(
        (
            job for job in jobs
            if job.get("title") == "Business Operations & Systems"
        ),
        None,
    )

    if job is None:
        raise SystemExit("Stedi position not found.")

    posting = format_job_for_evaluation("Stedi", job)

    print("Found:", job["title"])
    print("Description length:", len(posting))

    confirmation = input(
        "Run all four AI agents? This uses API credits. [y/N]: "
    )

    if confirmation.strip().lower() != "y":
        raise SystemExit("Evaluation cancelled.")

    result = evaluate_job(posting)

    # Preserve the original posting for our database.
    result["raw_posting"] = posting

    # Save the evaluation and application tracking record.
    initialize_database()
    save_evaluation(result)

    print("\n===== DISCOVERED JOB EVALUATION =====")
    print("Company:", result["job"]["company"])
    print("Title:", result["job"]["title"])
    print("Initial score:", result["initial_score"])
    print("Reviewed score:", result["reviewed_score"])
    print("Recommendation:", result["recommendation"])
    print("Apply:", job.get("applyUrl"))
