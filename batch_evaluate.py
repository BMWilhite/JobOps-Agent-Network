import json
import re
import sqlite3
from contextlib import closing
from discovery_history import (
    ensure_discovery_history_table,
    classify_discovered_candidates,
    record_displayed_job,
    partition_displayed_candidates,
)

from pathlib import Path
from greenhouse_discovery import (
    fetch_greenhouse_jobs,
    normalize_greenhouse_job,
)

from job_discovery import (
    fetch_ashby_jobs,
    get_tracked_titles,
    geographic_priority,
    travel_priority,
    compensation_priority,
    get_tracked_posting_urls,
    normalize_posting_url,
)
from job_discovery import format_job_for_evaluation
from orchestrator import evaluate_job
from database import DB_PATH, initialize_database
from save_evaluation import save_evaluation
from briefing import show_briefing

ROLE_KEYWORDS = (
    "business operations",
    "strategy & operations",
    "operations manager",
    "operations lead",
    "chief of staff",
    "implementation",
    "program manager",
    "project manager",
    "strategy",
)


def find_candidates():
    """Find new jobs worth considering for AI evaluation."""

    boards_path = Path(__file__).with_name("boards.json")
    boards = json.loads(
        boards_path.read_text(encoding="utf-8")
    )

    candidates = []

    tracked_urls = get_tracked_posting_urls()

    for company, board_name in boards.items():
        try:
            jobs = fetch_ashby_jobs(board_name)
        except Exception as error:
            print(f"Skipped {company}: {error}")
            continue

        tracked_titles = get_tracked_titles(company)

        for job in jobs:
            title = (job.get("title") or "").strip().casefold()


            posting_url = job.get("jobUrl") or job.get("applyUrl")

            if normalize_posting_url(posting_url) in tracked_urls:
                continue

            if not any(word in title for word in ROLE_KEYWORDS):
                continue

            if title in tracked_titles:
                continue

            geography = geographic_priority(job)
            travel = travel_priority(job)

            if geography.startswith((
                "Outside US",
                "Location-restricted",
                "Special Relocation",
            )):
                continue

            if travel.startswith("High travel"):
                continue

            candidates.append((company, job, geography, travel))

    # Discover additional opportunities through Greenhouse.

    greenhouse_path = Path(__file__).with_name(
        "greenhouse_boards.json"
    )

    greenhouse_boards = json.loads(
        greenhouse_path.read_text(encoding="utf-8")
    )

    for company, board_name in greenhouse_boards.items():
        try:
            greenhouse_jobs = fetch_greenhouse_jobs(board_name)
        except Exception as error:
            print(f"Skipped Greenhouse {company}: {error}")
            continue

        tracked_titles = get_tracked_titles(company)

        for original in greenhouse_jobs:
            job = normalize_greenhouse_job(original)

            if normalize_posting_url(job.get("jobUrl")) in tracked_urls:
                continue

            title = job["title"].strip().casefold()

            if not any(word in title for word in ROLE_KEYWORDS):
                continue

            if title in tracked_titles:
                continue

            location = job["location"].casefold()

            # A nationwide location does not prove remote work.
            if location.strip() in ("united states", "usa", "us"):

                geography = "Work arrangement unknown - Verify"
            else:
                geography = geographic_priority(job)

            if geography.startswith((
                "Outside US",
                "Location-restricted",
                "Special Relocation",
            )):
                continue

            travel = travel_priority(job)

            if travel.startswith("High travel"):
                continue

            candidates.append((company, job, geography, travel))

    return candidates

def priority_score(candidate):
    """Estimate review priority without calling AI."""

    company, job, geography, travel = candidate
    title = (job.get("title") or "").casefold()


    score = 0

    # Prioritize practical work locations.
    if geography.startswith("Preferred - US remote"):
        score += 5
    elif geography.startswith("Preferred - Arizona"):
        score += 5
    elif geography.startswith((
        "Relocation Option - Oregon",
        "Relocation Option - Washington",
    )):
        score += 3
    elif geography.startswith("Remote - Verify US eligibility"):
        score += 1
    elif geography.startswith("Work arrangement unknown"):
        score -= 3


    # Favor roles aligned with the target career path.
    if "chief of staff" in title:
        score += 6
    elif "business operations" in title:
        score += 6
    elif (
        "strategy & operations" in title
        or "strategy and operations" in title
    ):
        score += 5
    elif "operations lead" in title or "implementation" in title:
        score += 4
    elif "operations" in title:
        score += 3
    else:
        score += 1

    # Distinguish operations roles from product management.
    # Product management is a separate career discipline.
    if "product manager" in title or "product management" in title:
        score -= 6

    # Flag specialized or unusually senior positions.
    if any(word in title for word in (
        "director", "principal", "staff technical"
    )):
        score -= 3

    if any(word in title for word in (
        "clinical", "payer", "revenue", "monetization"
    )):
        score -= 2

    # Compensation matters, but cannot outweigh role fit.
    compensation = compensation_priority(job)

    if "Strong compensation fit" in compensation:
        score += 2
    elif "Potential compensation fit" in compensation:
        score += 1
    elif "Below preferred range" in compensation:
        score -= 2


    # Identify demanding qualifications in job description bullets.
    requirements = [
        line.strip().casefold()
        for line in (job.get("descriptionPlain") or "").splitlines()
        if line.strip().startswith(("-", "•"))
    ]

    # High-growth experience requirements can be a stretch.
    if any(
        "5+ years" in line and "high-growth" in line
        for line in requirements
    ):
        score -= 3

    # Explicit 8+ year experience requirements are a stretch.
    description_lines = (
        job.get("descriptionPlain") or ""
    ).casefold().splitlines()

    if any(
        re.search(
            r"\b(?:8|9|1[0-9])\s*\+?\s*years?\b",
            line,
        )
        and "experience" in line
        for line in description_lines
    ):
        score -= 4

    # Advanced data-tool proficiency may require further training.
    if any(
        "proficient" in line and "data tools" in line
        for line in requirements
    ):
        score -= 2

    return score


if __name__ == "__main__":
    MAX_EVALUATIONS = 2


    candidates = find_candidates()

    # Persist discovery history between separate runs.
    with closing(sqlite3.connect(DB_PATH)) as connection:
        with connection:
            ensure_discovery_history_table(connection)

            new_candidates, seen_candidates = (
                classify_discovered_candidates(
                    connection, candidates
                )
            )

    print("\n===== DISCOVERY HISTORY =====")
    print("New to JobOps:", len(new_candidates))
    print("Previously seen:", len(seen_candidates))


    # Show newly discovered jobs first.
    # Rank jobs within each group by priority.

    # Separate previously discovered jobs by display history.
    with closing(sqlite3.connect(DB_PATH)) as connection:
        undisplayed_candidates, displayed_candidates = (
            partition_displayed_candidates(
                connection, seen_candidates
            )
        )

    # Prioritize new jobs, then jobs not yet shown.
    new_candidates.sort(key=priority_score, reverse=True)
    undisplayed_candidates.sort(
        key=priority_score, reverse=True
    )
    displayed_candidates.sort(
        key=priority_score, reverse=True
    )


    # Daily shortlist includes only jobs not previously shown.
    # Previously displayed jobs remain saved in SQLite.
    candidates = new_candidates + undisplayed_candidates

    # Free discovery preview before any AI evaluations.
    print("\n===== UNSEEN OPPORTUNITIES (UP TO 10) =====")

    for rank, candidate in enumerate(candidates[:10], start=1):
        company, job, geography, travel = candidate

        print(f"\n{rank}. {company} - {job.get('title')}")

        if rank <= len(new_candidates):
            status = "NEW TO JOBOPS"
        elif rank <= (
            len(new_candidates) + len(undisplayed_candidates)
        ):
            status = "NOT YET DISPLAYED"
        else:
            status = "Previously displayed"

        print(f"   Discovery: {status}")
        print(f"   Compensation: {compensation_priority(job)}")
        print(f"   Geography: {geography}")
        print(f"   Travel: {travel}")
        print(
            f"   Link: "
            f"{job.get('jobUrl') or job.get('applyUrl') or 'Unavailable'}"
        )


    # Remember the jobs actually shown in this briefing.
    with closing(sqlite3.connect(DB_PATH)) as connection:
        with connection:
            ensure_discovery_history_table(connection)

            for _, job, _, _ in candidates[:10]:
                record_displayed_job(connection, job)

    print(
        "\nOpportunities displayed this run:",
        min(10, len(candidates)),
    )

    print("\nThese are preliminary rankings, not AI fit scores.")

    # Skip the selection menu when there are no unseen jobs.
    if not candidates:
        print("\nNo new or previously unseen opportunities.")
        print("All currently eligible postings have been displayed.")
        print("\nShowing your existing application briefing...")
        show_briefing()
        raise SystemExit(0)

    print("\n===== SELECT JOBS FOR AI EVALUATION =====")
    print("Choose up to 2 jobs from the Top 10.")
    print("Example: 1,4")
    print("Press Enter to skip paid evaluations.")

    choices = input("\nYour selection: ").strip()

    if not choices:
        print("\nNo AI evaluations selected.")
        show_briefing()
        raise SystemExit(0)

    try:
        numbers = [
            int(value.strip())
            for value in choices.split(",")
        ]
    except ValueError:
        raise SystemExit(
            "Invalid selection. Enter numbers like 1,4."
        )

    if (
        len(numbers) > MAX_EVALUATIONS
        or len(numbers) != len(set(numbers))
        or any(
            number < 1 or number > min(10, len(candidates))
            for number in numbers
        )
    ):
        raise SystemExit(
            "Select one or two different jobs from the Top 10."
        )

    selected = [
        candidates[number - 1]
        for number in numbers
    ]

    print(f"\nEligible opportunities: {len(candidates)}")
    print(f"Selected for evaluation: {len(selected)}")

    for company, job, geography, travel in selected:
        print(f"\n{company} - {job['title']}")
        print("Geography:", geography)
        print("Compensation:", compensation_priority(job))
        print("Travel:", travel)
        print("Apply:", job.get("applyUrl"))

    confirmation = input(
        "\nEvaluate these jobs with AI? [y/N]: "
    )


    if confirmation.strip().lower() != "y":
        print("\nAI evaluations skipped.")
        print("Showing your existing application briefing...")
        show_briefing()
        raise SystemExit(0)

    initialize_database()

    for company, job, geography, travel in selected:
        print(f"\nEvaluating {company} - {job['title']}")

        try:
            posting = format_job_for_evaluation(company, job)

            result = evaluate_job(posting)
            result["raw_posting"] = posting

            save_evaluation(result)

            print("Completed:", company, job["title"])
            print("Score:", result["reviewed_score"])
            print("Recommendation:", result["recommendation"])

        except Exception as error:
            print(f"Evaluation failed: {error}")
            print("Continuing to next job...")

    print("\nBatch evaluation finished.")
    show_briefing()