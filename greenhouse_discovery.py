
"""Retrieve public job listings from Greenhouse boards."""
from html import unescape
import json
import re
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import quote


def fetch_greenhouse_jobs(board_name):
    """Return published jobs from a Greenhouse employer."""

    board = quote(board_name, safe="")

    url = (
        "https://boards-api.greenhouse.io/v1/boards/"
        f"{board}/jobs?content=true"
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

    jobs = data.get("jobs", [])

    if not isinstance(jobs, list):
        raise ValueError("Unexpected Greenhouse response")

    return jobs


class GreenhouseTextParser(HTMLParser):
    """Convert job-description HTML into readable text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag in (
            "p", "br", "div", "li", "h1", "h2", "h3", "h4"
        ):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip_depth = max(0, self.skip_depth - 1)
        elif self.skip_depth == 0 and tag in (
            "p", "div", "li", "h1", "h2", "h3", "h4"
        ):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0:
            self.parts.append(data)

    def get_text(self):
        return "\n".join(
            line.strip()
            for line in "".join(self.parts).splitlines()
            if line.strip()
        )


def normalize_greenhouse_job(job):
    """Convert Greenhouse data to JobOps' existing format."""

    parser = GreenhouseTextParser()

    parser.feed(unescape(job.get("content") or ""))

    location = (job.get("location") or {}).get("name")

    workplace = (
        "Remote"
        if "remote" in (location or "").casefold()
        else "Unknown"
    )

    return {
        "source": "greenhouse",
        "source_job_id": str(job.get("id")),
        "title": job.get("title") or "Unknown",
        "location": location or "Unknown",
        "workplaceType": workplace,
        "descriptionPlain": parser.get_text(),
        "jobUrl": job.get("absolute_url"),
        "applyUrl": job.get("absolute_url"),
        "compensation": {},
        "published_pay_range": extract_greenhouse_pay_range(
            parser.get_text()
        ),
    }

def extract_greenhouse_pay_range(description):
    """Extract explicitly labeled compensation ranges."""

    text = " ".join((description or "").split())

    pattern = (
        r"(?:Base Pay Range|Our range for this role is)"
        r"\s*:?\s*"
        r"\$\s*(\d{2,3}(?:,\d{3})+)"
        r"\s*[-–—]\s*"
        r"\$?\s*(\d{2,3}(?:,\d{3})+)"
    )

    match = re.search(pattern, text, flags=re.IGNORECASE)

    if not match:
        return None

    minimum = int(match.group(1).replace(",", ""))
    maximum = int(match.group(2).replace(",", ""))

    # Reject implausible values or reversed ranges.
    if not (30000 <= minimum <= maximum <= 1000000):
        return None

    return {
        "minimum": minimum,
        "maximum": maximum,
        "display": f"${minimum:,} - ${maximum:,}",
    }

if __name__ == "__main__":
    jobs = fetch_greenhouse_jobs("candid")

    keywords = (
        "operations",
        "strategy",
        "implementation",
        "chief of staff",
        "program manager",
    )

    matches = [
        job for job in jobs
        if any(
            word in job.get("title", "").casefold()
            for word in keywords
        )
    ]

    print("Greenhouse discovery module working!")
    print("Total published jobs:", len(jobs))
    print("Relevant title matches:", len(matches))

    for job in matches:
        print("\nTitle:", job.get("title"))
        print("Job ID:", job.get("id"))
        print("Location:", job.get("location", {}).get("name"))
        print("URL:", job.get("absolute_url"))
