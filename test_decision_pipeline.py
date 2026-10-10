
import json
import sqlite3
import tempfile
from copy import deepcopy
from contextlib import closing
from pathlib import Path

import database
import save_evaluation as saver
from decision_rules import decide_recommendation



source = json.loads(
    Path("example_evaluation.json").read_text(
        encoding="utf-8"
    )
)

high_scores = {
    "hard_requirements": 26,
    "work_shape": 22,
    "relevant_experience": 13,
    "compensation": 9,
    "geography": 7,
    "mission_and_trajectory": 8,
}

medium_scores = {
    "hard_requirements": 20,
    "work_shape": 17,
    "relevant_experience": 10,
    "compensation": 7,
    "geography": 5,
    "mission_and_trajectory": 6,
}

low_scores = {
    "hard_requirements": 15,
    "work_shape": 14,
    "relevant_experience": 9,
    "compensation": 5,
    "geography": 6,
    "mission_and_trajectory": 6,
}

scenarios = [
    ("Strong candidate", high_scores, ["None found"], "Apply", "Apply"),
    ("Real blocker", high_scores, ["Required license missing"], "Apply", "Hold"),
    ("Borderline candidate", medium_scores, [], "Apply", "Hold"),
    ("Low score", low_scores, [], "Apply", "Skip"),
]

with tempfile.TemporaryDirectory() as folder:
    test_db = Path(folder) / "decision_test.db"

    database.DB_PATH = test_db
    saver.DB_PATH = test_db
    database.initialize_database()

    for name, scores, blockers, strategist, expected in scenarios:
        data = deepcopy(source)

        data["job"]["company"] = "JobOps Test"
        data["job"]["title"] = name
        data["raw_posting"] = f"SYNTHETIC TEST: {name}"

        data["review"]["revised_scores"] = scores
        data["review"]["confirmed_hard_blockers"] = blockers
        data["strategy"]["recommendation"] = strategist

        data["recommendation"] = decide_recommendation(
            sum(scores.values()),
            blockers,
            strategist,
        )

        assert data["recommendation"] == expected

        saver.save_evaluation(data)

        with closing(sqlite3.connect(test_db)) as conn:
            saved = conn.execute(
                """
                SELECT e.recommendation
                FROM evaluations e
                JOIN jobs j ON j.id = e.job_id
                WHERE j.title = ?
                ORDER BY e.id DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()

        assert saved is not None
        assert saved[0] == expected, (
            f"{name}: expected {expected}, saved {saved[0]}"
        )

        print(f"PASS: {name} -> {saved[0]}")

print("\nALL DECISION PIPELINE TESTS PASSED")
print("Real jobops.db unchanged.")
