from contextlib import closing
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("jobops.db")


def initialize_database():

    conn = sqlite3.connect(DB_PATH)
    with closing(conn), conn:

        conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                location TEXT,
                work_arrangement TEXT,
                salary_min INTEGER,
                salary_max INTEGER,
                description TEXT NOT NULL,
                extracted_details TEXT,
                status TEXT DEFAULT 'New',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                initial_score INTEGER,
                reviewed_score INTEGER,
                recommendation TEXT,
                strengths TEXT,
                gaps TEXT,
                blockers TEXT,
                reviewer_notes TEXT,
                score_breakdown TEXT,
                resume_angle TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                status TEXT DEFAULT 'Not Applied',
                applied_date TEXT,
                notes TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );
        """)

    print("JobOps database initialized successfully!")
    print(f"Database location: {DB_PATH}")


if __name__ == "__main__":
    initialize_database()
