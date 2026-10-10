
import json
import sqlite3
from textwrap import shorten

from database import DB_PATH


def show_briefing(new_discoveries=None, shown_this_run=None):
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

    # Show cumulative discovery history when tracking tables exist.
    with sqlite3.connect(DB_PATH) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        if {"discovered_jobs", "displayed_jobs"}.issubset(tables):
            discovered = connection.execute(
                "SELECT COUNT(*) FROM discovered_jobs"
            ).fetchone()[0]

            unseen = connection.execute(
                """
                SELECT COUNT(*)
                FROM discovered_jobs AS d
                LEFT JOIN displayed_jobs AS s
                    ON s.normalized_url = d.normalized_url
                WHERE s.normalized_url IS NULL
                """
            ).fetchone()[0]

            print("\n===== JOBOPS DISCOVERY SNAPSHOT =====")
            print(f"Total jobs discovered: {discovered}")
            print(f"Previously displayed: {discovered - unseen}")
            print(f"Not yet displayed: {unseen}")

    if new_discoveries is not None and shown_this_run is not None:
        print("\n===== CURRENT SCAN =====")
        print(f"New eligible discoveries: {new_discoveries}")
        print(f"Previously unseen jobs shown: {shown_this_run}")

    print("\n===== JOBOPS APPLICATION BRIEFING =====")
    print(f"Opportunities for review: {len(jobs)}")

    ready_to_apply = sum(
        1 for job in jobs if job[3] == "Apply"
    )
    on_hold = sum(
        1 for job in jobs if job[3] == "Hold"
    )

    print(f"Ready to apply: {ready_to_apply}")
    print(f"On hold for review: {on_hold}")

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
        action = (
            "Prepare application"
            if decision == "Apply"
            else "Review fit concerns"
        )
        print(f"   Next action: {action}")
        print(
            "   Reviewer summary:",
            shorten(reasoning, width=160, placeholder="..."),
        )

        strategy_reason = reviewer.get("strategy_reason", "")

        if strategy_reason:
            strategy_reason = " ".join(
                strategy_reason.split()
            )
            print(
                "   Strategy:",
                shorten(strategy_reason, width=160, placeholder="..."),
            )
        else:
            print("   Strategy: Not saved in earlier evaluation")
        print(f"   Application: {url or 'URL unavailable'}")
        print("-" * 50)


if __name__ == "__main__":
    show_briefing()
