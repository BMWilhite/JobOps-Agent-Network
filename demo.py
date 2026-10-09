
import json
from pathlib import Path

from orchestrator import evaluate_job


def run_demo():
    project_dir = Path(__file__).resolve().parent

    # Use fictional public demonstration files.
    profile_path = project_dir / "candidate_profile.example.md"
    posting_path = project_dir / "job_posting.example.txt"

    posting = posting_path.read_text(
        encoding="utf-8"
    )

    print("Starting fictional JobOps demonstration...\n")

    # Run four agents using the fictional profile.
    result = evaluate_job(
        posting,
        profile_path=profile_path,
    )

    # Save public example output.
    output_path = project_dir / "example_evaluation.json"

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n===== DEMONSTRATION RESULTS =====")
    print("Company:", result["job"]["company"])
    print("Title:", result["job"]["title"])
    print("Initial score:", result["initial_score"])
    print("Reviewed score:", result["reviewed_score"])
    print("Recommendation:", result["recommendation"])
    print("\nExample saved to:", output_path)


if __name__ == "__main__":
    run_demo()
