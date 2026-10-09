
import json
import sqlite3
from pathlib import Path

from database import DB_PATH, initialize_database


def save_evaluation():
    # Load the previously saved AI evaluation.
    file_path = Path(__file__).with_name(
        "latest_evaluation.json"
    )

    data = json.loads(
        file_path.read_text(encoding="utf-8")
    )

    job = data["job"]
    analyst = data["initial_assessment"]
    review = data["review"]
    strategy = data["strategy"]

    # Recover uncapped scores from the agent outputs.
    initial_score = sum(analyst["scores"].values())
    reviewed_score = sum(
        review["revised_scores"].values()
    )

    # Treat AI-claimed blockers as unverified.
    claimed_blockers = review["confirmed_hard_blockers"]

    if reviewed_score < 60:
        recommendation = "Skip"
    elif claimed_blockers:
        recommendation = "Hold"
    elif reviewed_score < 70 and data["recommendation"] == "Apply":
        recommendation = "Hold"
    else:
        recommendation = data["recommendation"]

    # Keep the audit history.
    reviewer_notes = {
        "reasoning": review["review_reasoning"],
        "disputed_claims": review["disputed_claims"],
        "unresolved_questions": review["unresolved_questions"],
        "original_recommendation": data["recommendation"],
        "import_note": (
            "Prior evaluation imported with uncapped scores. "
            "AI-claimed blockers require independent verification. "
            "Reevaluation under revised rules is pending."
        ),
    }

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        # Avoid importing the exact same posting twice.
        existing = conn.execute(
            """
            SELECT id FROM jobs
            WHERE company = ?
              AND title = ?
              AND description = ?
            """,
            (
                job["company"],
                job["title"],
                data["raw_posting"],
            ),
        ).fetchone()

        if existing:
            print(
                f"Job already exists with ID {existing[0]}."
            )
            return

        # Insert the job posting.
        cursor = conn.execute(
            """
            INSERT INTO jobs (
                company, title, url, location,
                work_arrangement, salary_min, salary_max,
                description, extracted_details, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["company"],
                job["title"],
                job.get("url"),
                job.get("location"),
                job.get("work_arrangement"),
                job.get("salary_min"),
                job.get("salary_max"),
                data["raw_posting"],
                json.dumps(job),
                "Needs Review" if claimed_blockers else "New",
            ),
        )

        job_id = cursor.lastrowid

        # Insert the AI evaluation.
        conn.execute(
            """
            INSERT INTO evaluations (
                job_id, initial_score, reviewed_score,
                recommendation, strengths, gaps,
                blockers, reviewer_notes,
                score_breakdown, resume_angle
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                initial_score,
                reviewed_score,
                recommendation,
                json.dumps(review["justified_strengths"]),
                json.dumps(review["gaps_not_blockers"]),
                json.dumps({
                    "claimed_unverified": claimed_blockers
                }),
                json.dumps(reviewer_notes),
                json.dumps({
                    "initial": analyst["scores"],
                    "reviewed": review["revised_scores"],
                }),
                strategy["resume_positioning"],
            ),
        )

        # Create an application tracking record.
        conn.execute(
            """
            INSERT INTO applications (job_id, status)
            VALUES (?, ?)
            """,
            (job_id, "Not Applied"),
        )

    print("\nJob saved successfully!")
    print(f"Database job ID: {job_id}")
    print(f"Company: {job['company']}")
    print(f"Title: {job['title']}")
    print(f"Initial score: {initial_score}")
    print(f"Reviewed score: {reviewed_score}")
    print(f"Recommendation: {recommendation}")
    print("Application status: Not Applied")


if __name__ == "__main__":
    initialize_database()
    save_evaluation()
