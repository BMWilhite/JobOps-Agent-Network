
from job_discovery import normalize_posting_url

"""Track job postings discovered across multiple scans."""

def ensure_discovery_history_table(connection):
    """Create discovery and display tracking tables."""

    connection.execute("""
        CREATE TABLE IF NOT EXISTS discovered_jobs (
            normalized_url TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            first_seen_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS displayed_jobs (
            normalized_url TEXT PRIMARY KEY,
            first_displayed_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
    """)

def record_discovered_job(connection, company, job):

    """Record a posting and return True if it is newly discovered."""

    url = job.get("jobUrl") or job.get("applyUrl")
    title = (job.get("title") or "").strip()

    if not url or not title:
        raise ValueError("Discovered job needs a URL and title.")

    normalized_url = normalize_posting_url(url)

    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO discovered_jobs
            (normalized_url, company, title)
        VALUES (?, ?, ?)
        """,
        (normalized_url, company, title),
    )

    if cursor.rowcount == 1:
        return True

    connection.execute(
        """
        UPDATE discovered_jobs
        SET company = ?,
            title = ?,
            last_seen_at = CURRENT_TIMESTAMP
        WHERE normalized_url = ?
        """,
        (company, title, normalized_url),
    )

def classify_discovered_candidates(connection, candidates):
    """Separate newly discovered postings from previously seen ones."""

    new_candidates = []
    seen_candidates = []

    for candidate in candidates:
        company, job, geography, travel = candidate

        is_new = record_discovered_job(
            connection,
            company,
            job,
        )

        if is_new:
            new_candidates.append(candidate)
        else:
            seen_candidates.append(candidate)

    return new_candidates, seen_candidates

    return False

def record_displayed_job(connection, job):
    """Record when a job is first shown to the user."""

    url = job.get("jobUrl") or job.get("applyUrl")

    if not url:
        raise ValueError("Displayed job needs a URL.")

    normalized_url = normalize_posting_url(url)

    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO displayed_jobs
            (normalized_url)
        VALUES (?)
        """,
        (normalized_url,),
    )

    return cursor.rowcount == 1

def partition_displayed_candidates(connection, candidates):
    """Separate unseen opportunities from previously displayed ones."""

    displayed_urls = {
        row[0]
        for row in connection.execute(
            "SELECT normalized_url FROM displayed_jobs"
        )
    }

    undisplayed = []
    previously_displayed = []

    for candidate in candidates:
        company, job, geography, travel = candidate

        url = job.get("jobUrl") or job.get("applyUrl")

        if url and normalize_posting_url(url) in displayed_urls:
            previously_displayed.append(candidate)
        else:
            undisplayed.append(candidate)

    return undisplayed, previously_displayed
