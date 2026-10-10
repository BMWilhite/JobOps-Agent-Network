
import json
import sqlite3

from database import DB_PATH


def show_briefing():
    """Display ranked, unapplied job opportunities."""

    with sqlite3.connect(DB_PATH) as connection:
        jobs = connection.execute(
            """
            SELECT
                j.company,
                j.title,
                e.reviewed_score,
                e.recommendation,
                j.url,
                e.reviewer_notes
            FROM jobs AS j
            JOIN evaluations AS e ON e.job_id = j.id
            JOIN applications AS a ON a.job_id = j.id

WHERE a.status = 'Not Applied'
  AND COALESCE(j.status, '') NOT IN ('Not Listed', 'Closed')
  AND e.recommendation IN ('Apply', 'Hold')
            ORDER BY
                CASE e.recommendation
                    WHEN 'Apply' THEN 0
                    ELSE 1
                END,
                e.reviewed_score DESC,
                j.id ASC
            """
        ).fetchall()

    print("\n===== JOBOPS APPLICATION BRIEFING =====")
    print(f"Opportunities for review: {len(jobs)}")

    if not jobs:
        print("No unapplied Apply/Hold opportunities found.")
        return

    for number, row in enumerate(jobs, start=1):
        company, title, score, decision, url, notes = row

        reviewer = json.loads(notes or "{}")
        reasoning = reviewer.get(
            "reasoning", "No reviewer notes recorded."
        )

        reasoning = " ".join(reasoning.split())

        print(f"\n{number}. {company} - {title}")
        print(f"   Score: {score}/100")
        print(f"   Recommendation: {decision}")
        print(f"   Reviewer: {reasoning[:300]}")

        strategy_reason = reviewer.get("strategy_reason", "")

        if strategy_reason:
            strategy_reason = " ".join(
                strategy_reason.split()
            )
            print(f"   Strategy: {strategy_reason[:300]}")
        else:
            print("   Strategy: Not saved in earlier evaluation")
        print(f"   Application: {url or 'URL unavailable'}")
        print("-" * 50)


if __name__ == "__main__":
    show_briefing()
