"""Additive MVP tables. Existing jobs, evaluations and applications are never rewritten."""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
from pathlib import Path

from job_discovery import normalize_posting_url


def stable_job_id(company, job):
    url = normalize_posting_url(job.get("jobUrl") or job.get("applyUrl"))
    source_id = job.get("source_job_id") or job.get("id")
    if url:
        identity = url
    elif source_id:
        identity = f"{company.casefold()}:{job.get('source', 'ashby')}:{source_id}"
    else:
        raise ValueError("Job has neither a posting URL nor a source identifier.")
    return hashlib.sha256(identity.encode()).hexdigest()


class JobOpsStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS mvp_jobs (
                    id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Active',
                    reevaluate INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                    displayed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS mvp_screenings (
                    id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES mvp_jobs(id),
                    cache_key TEXT NOT NULL, mode TEXT NOT NULL, result TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS mvp_screening_cache
                    ON mvp_screenings(job_id, cache_key, mode);
                CREATE TABLE IF NOT EXISTS mvp_feedback (
                    id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES mvp_jobs(id),
                    correction TEXT NOT NULL, expected TEXT NOT NULL,
                    snapshot TEXT NOT NULL, report TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS mvp_packages (
                    id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES mvp_jobs(id),
                    folder TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Import a view of prior jobs and their latest evaluations, preserving all original rows.
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='jobs'").fetchone():
                for row in conn.execute("SELECT * FROM jobs").fetchall():
                    job = dict(row)
                    payload = {"title": job["title"], "jobUrl": job.get("url"),
                               "applyUrl": job.get("url"), "location": job.get("location"),
                               "descriptionPlain": job["description"], "source": "legacy",
                               "source_job_id": str(job["id"]),
                               "salary_min": job.get("salary_min"), "salary_max": job.get("salary_max")}
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='evaluations'").fetchone():
                        evaluation = conn.execute("SELECT * FROM evaluations WHERE job_id=? ORDER BY id DESC LIMIT 1", (job["id"],)).fetchone()
                        payload["legacy_evaluation"] = dict(evaluation) if evaluation else None
                    key = stable_job_id(job["company"], payload)
                    conn.execute("INSERT OR IGNORE INTO mvp_jobs(id,company,title,payload) VALUES(?,?,?,?)",
                                 (key, job["company"], job["title"], json.dumps(payload)))

    def upsert_candidates(self, candidates):
        inserted = 0
        with self.connect() as conn:
            for company, job, geography, travel in candidates:
                key = stable_job_id(company, job)
                previous = conn.execute("SELECT payload FROM mvp_jobs WHERE id=?", (key,)).fetchone()
                payload = dict(job, geography=geography, travel=travel)
                if previous:
                    legacy = json.loads(previous["payload"]).get("legacy_evaluation")
                    if legacy:
                        payload["legacy_evaluation"] = legacy
                else:
                    inserted += 1
                conn.execute("""INSERT INTO mvp_jobs(id,company,title,payload) VALUES(?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET company=excluded.company,title=excluded.title,
                    payload=excluded.payload,last_seen=CURRENT_TIMESTAMP""",
                             (key, company, job["title"], json.dumps(payload, ensure_ascii=False)))
        return inserted

    def jobs(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM mvp_jobs ORDER BY last_seen DESC, company, title").fetchall()
        return [dict(json.loads(r["payload"]), id=r["id"], company=r["company"],
                     title=r["title"], status=r["status"], reevaluate=bool(r["reevaluate"]),
                     displayed_at=r["displayed_at"]) for r in rows]

    def mark_displayed(self, job_id):
        with self.connect() as conn:
            conn.execute("UPDATE mvp_jobs SET displayed_at=COALESCE(displayed_at,CURRENT_TIMESTAMP) WHERE id=?", (job_id,))

    def set_status(self, job_id, status):
        if status not in ("Active", "Dismissed", "Rejected"):
            raise ValueError("Invalid opportunity status.")
        with self.connect() as conn:
            conn.execute("UPDATE mvp_jobs SET status=? WHERE id=?", (status, job_id))

    def request_reevaluation(self, job_id):
        with self.connect() as conn:
            conn.execute("UPDATE mvp_jobs SET reevaluate=1 WHERE id=?", (job_id,))

    def screening(self, job_id, key=None, *, ai_only=False):
        with self.connect() as conn:
            sql = "SELECT * FROM mvp_screenings WHERE job_id=?"
            args = [job_id]
            if key:
                sql += " AND cache_key=?"
                args.append(key)
            if ai_only:
                sql += " AND mode='ai'"
            sql += " ORDER BY id DESC LIMIT 1"
            row = conn.execute(sql, args).fetchone()
        return dict(row, result=json.loads(row["result"])) if row else None

    def save_screening(self, job_id, key, mode, result):
        if mode not in ("ai", "local"):
            raise ValueError("Unknown screening mode.")
        with self.connect() as conn:
            conn.execute("INSERT INTO mvp_screenings(job_id,cache_key,mode,result) VALUES(?,?,?,?)",
                         (job_id, key, mode, json.dumps(result, ensure_ascii=False)))
            if mode == "ai":
                conn.execute("UPDATE mvp_jobs SET reevaluate=0 WHERE id=?", (job_id,))

    def screening_history(self, job_id):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM mvp_screenings WHERE job_id=? ORDER BY id DESC", (job_id,)).fetchall()
        return [dict(r, result=json.loads(r["result"])) for r in rows]

    def add_feedback(self, job, screening, correction, expected):
        if not correction.strip():
            raise ValueError("Describe the correction before saving feedback.")
        from feedback_report import diagnostic_report
        snapshot = {"job": job, "original_screening": screening}
        report = diagnostic_report(snapshot, correction.strip(), expected)
        with self.connect() as conn:
            cursor = conn.execute("INSERT INTO mvp_feedback(job_id,correction,expected,snapshot,report) VALUES(?,?,?,?,?)",
                                  (job["id"], correction.strip(), expected, json.dumps(snapshot), json.dumps(report)))
            return cursor.lastrowid

    def feedback(self, job_id):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM mvp_feedback WHERE job_id=? ORDER BY id DESC", (job_id,)).fetchall()
        return [dict(r, snapshot=json.loads(r["snapshot"]), report=json.loads(r["report"])) for r in rows]

    def save_package(self, job_id, folder):
        with self.connect() as conn:
            conn.execute("INSERT INTO mvp_packages(job_id,folder) VALUES(?,?)", (job_id, str(folder)))

    def packages(self, job_id):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM mvp_packages WHERE job_id=? ORDER BY id DESC", (job_id,))]
