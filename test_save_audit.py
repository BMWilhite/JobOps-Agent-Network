
import json
import sqlite3
import tempfile
from pathlib import Path

import database
import save_evaluation as saver


# Reuse an existing evaluation. No AI calls needed.

data = json.loads(
    Path("example_evaluation.json").read_text(
        encoding="utf-8"
    )
)

# Supply a fictional posting for the public test.
data["raw_posting"] = (
    "SYNTHETIC TEST JOB: Operations role at a fictional "
    "company. Used only to verify database persistence."
)

# Use a disposable database, never the real jobops.db.
with tempfile.TemporaryDirectory() as temp_folder:
    test_db = Path(temp_folder) / "jobops_audit_test.db"

    database.DB_PATH = test_db
    saver.DB_PATH = test_db

    database.initialize_database()
    saver.save_evaluation(data)

    with sqlite3.connect(test_db) as connection:
        row = connection.execute(
            """
            SELECT reviewer_notes
            FROM evaluations
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    connection.close()

    assert row is not None, "No evaluation was saved."

    notes = json.loads(row[0])

    assert notes["reasoning"] == (
        data["review"]["review_reasoning"]
    )

    assert notes["strategy_reason"] == (
        data["strategy"]["recommendation_reason"]
    )

    assert notes["final_recommendation"] == (
        data["recommendation"]
    )

    print("\nAUDIT SAVE TEST PASSED")
    print("Reviewer reasoning: Saved correctly")
    print("Strategist reasoning: Saved correctly")
    print("Final recommendation: Saved correctly")
    print("Real jobops.db: Unchanged")
