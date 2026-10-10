
import json
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

import sqlite3
from pathlib import Path
from contextlib import closing
from database import DB_PATH


def fetch_ashby_jobs(board_name):
    """Retrieve published jobs from an Ashby career board."""

    url = (
        "https://api.ashbyhq.com/posting-api/job-board/"
        f"{board_name}?includeCompensation=true"
    )

    request = Request(
        url,
        headers={
            "User-Agent": "JobOps/0.2",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=20) as response:
        data = json.load(response)

    return [
        job for job in data["jobs"]
        if job.get("isListed", True)
    ]

def normalize_posting_url(url):
    """Remove tracking parameters and application-page suffixes."""

    if not url:
        return ""

    parsed = urlsplit(url.strip())

    domain = parsed.netloc.casefold()
    path = parsed.path.rstrip("/").casefold()

    # Ashby may link to either a posting or its application.
    if path.endswith("/application"):
        path = path[:-len("/application")]

    return f"{domain}{path}"


def get_tracked_posting_urls():
    """Return normalized URLs for previously saved jobs."""

    if not Path(DB_PATH).exists():
        return set()

    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            """
            SELECT url
            FROM jobs
            WHERE url IS NOT NULL
              AND TRIM(url) != ''
            """
        ).fetchall()

    return {
        normalize_posting_url(url)
        for (url,) in rows
        if normalize_posting_url(url)
    }

def get_tracked_titles(company):
    """Find positions already stored for a company."""

    database_path = Path(__file__).with_name("jobops.db")

    if not database_path.exists():
        return set()

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT title FROM jobs WHERE company = ? COLLATE NOCASE",
            (company,),
        ).fetchall()


    # Normalize titles that may include a "(Remote)" suffix.
    tracked = {
        title.strip().casefold().removesuffix(" (remote)").strip()
        for (title,) in rows
    }

    # Recognize both versions of each stored title.
    return tracked | {
        f"{title} (remote)"
        for title in tracked
    }

def geographic_priority(job):
    """Classify geography without assuming remote means US-wide."""

    workplace = (job.get("workplaceType") or "").casefold()
    location = (job.get("location") or "").casefold()

    outside_us = (
        "australia",
        "canada",
        "united kingdom",
        "europe",
        "india",
        "germany",
        "france",
    )

    if any(place in location for place in outside_us):
        return "Outside US - Review eligibility"

    if workplace == "remote":
        if "new york" in location or "california" in location:
            return "Location-restricted remote - Verify"

        us_markers = (
            "united states",
            "usa",
            "us-remote",
            "remote - us",
            "remote (us)",
            "us (remote)",
        )

        if any(marker in location for marker in us_markers):
            return "Preferred - US remote (verify states)"

        return "Remote - Verify US eligibility"

    if any(place in location for place in (
        "arizona", "tucson", "phoenix"
    )):
        return "Preferred - Arizona"

    if any(place in location for place in (
        "oregon", "portland"
    )):
        return "Relocation Option - Oregon"

    if any(place in location for place in (
        "washington", "seattle", "spokane", "tacoma"
    )):
        return "Relocation Option - Washington"

    return "Special Relocation Required"

    workplace = (job.get("workplaceType") or "").casefold()
    location = (job.get("location") or "").casefold()

    if workplace == "remote":
        return "Preferred - Remote"

    if "arizona" in location or "tucson" in location:
        return "Preferred - Arizona"

    if "oregon" in location or "portland" in location:
        return "Relocation Option - Oregon"

    if any(city in location for city in (
        "seattle", "spokane", "tacoma", "bellevue"
    )):
        return "Relocation Option - Washington"

    return "Special Relocation Required"


def compensation_priority(job):
    """Evaluate publicly listed annual USD base salary."""

    # Greenhouse publishes compensation in job-description text.
    published = job.get("published_pay_range")

    if published:
        return (
            f"{published['display']}"
            " | Published range (verify annual USD)"
        )

    if job.get("shouldDisplayCompensationOnJobPostings") is False:
        return "Salary not publicly disclosed"

    compensation = job.get("compensation") or {}
    components = compensation.get("summaryComponents") or []

    salaries = [
        component for component in components
        if component.get("compensationType") == "Salary"
        and component.get("interval") == "1 YEAR"
        and component.get("currencyCode") == "USD"
        and isinstance(component.get("minValue"), (int, float))
        and isinstance(component.get("maxValue"), (int, float))
    ]

    if not salaries:
        return "Salary unknown or not annual USD"

    minimum = min(item["minValue"] for item in salaries)
    maximum = max(item["maxValue"] for item in salaries)

    if minimum >= 130000:
        priority = "Strong compensation fit"
    elif maximum >= 130000:
        priority = "Potential compensation fit"
    else:
        priority = "Below preferred range"

    return (
        f"${minimum:,.0f} - ${maximum:,.0f}/year"
        f" | {priority}"
    )


def travel_priority(job):
    """Identify travel requirements mentioned in job descriptions."""

    import re

    description = job.get("descriptionPlain") or ""

    patterns = [
        r"\b(\d{1,3})\s*%\s*(?:of\s+)?travel\b",
        r"\btravel\s+(?:up to\s+)?(\d{1,3})\s*%",
    ]

    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)

        if match:
            percentage = int(match.group(1))

            if percentage >= 20:
                return f"High travel ({percentage}%) - Deprioritize"

            if percentage > 0:
                return f"Travel required ({percentage}%) - Review"

            return "No percentage-based travel required - Verify"

    if "travel" in description.lower():
        return "Travel mentioned - Manual review"

    return "Travel not specified"


def format_job_for_evaluation(company, job):
    """Convert an Ashby posting into readable text for our agents."""

    description = (job.get("descriptionPlain") or "").strip()

    if not description:
        raise ValueError("Job has no description to evaluate.")

    compensation = job.get("compensation") or {}
    salary = (
        compensation.get("compensationTierSummary")
        or "Not disclosed"
    )

    return (
        f"Company: {company}\n"
        f"Job title: {job.get('title', 'Unknown')}\n"
        f"Location: {job.get('location', 'Unknown')}\n"
        f"Work arrangement: {job.get('workplaceType', 'Unknown')}\n"
        f"Compensation: {salary}\n"
        f"Job URL: {job.get('jobUrl') or job.get('applyUrl')}\n\n"
        f"Full job description:\n{description}"
    )

if __name__ == "__main__":

    # Companies and their Ashby career board names.


    boards = json.loads(
        Path(__file__).with_name("boards.json").read_text(
            encoding="utf-8"
        )
    )

    role_keywords = (
        "business operations",
        "strategy & operations",
        "strategic operations",
        "operations manager",
        "operations lead",
        "chief of staff",
        "program manager",
        "project manager",
        "implementation",
        "strategy",
    )

    for company, board_name in boards.items():
        print(f"\nChecking {company}...")

        try:
            jobs = fetch_ashby_jobs(board_name)
        except Exception as error:
            print(f"Could not retrieve jobs: {error}")
            continue

        relevant_jobs = [
            job for job in jobs
            if any(
                keyword in job.get("title", "").lower()
                for keyword in role_keywords
            )
        ]

        tracked_titles = get_tracked_titles(company)

        new_jobs = [
            job for job in relevant_jobs
            if job.get("title", "").strip().casefold()
            not in tracked_titles
        ]

        print(f"Published jobs: {len(jobs)}")
        print(f"Potential matches: {len(relevant_jobs)}")
        print(f"New opportunities: {len(new_jobs)}")

        for job in new_jobs:
            print("\nTitle:", job.get("title"))
            print("Location:", job.get("location"))
            print("Type:", job.get("workplaceType"))
            print("Geography:", geographic_priority(job))
            print("Compensation:", compensation_priority(job))
            print("Travel:", travel_priority(job))
            print("Apply:", job.get("applyUrl"))
            print("-" * 40)
