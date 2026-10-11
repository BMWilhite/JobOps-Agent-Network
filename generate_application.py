import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from agents import Runner
from agents.exceptions import ModelBehaviorError

from application_documents import ApplicationDocuments, application_document_writer
from application_evidence import (document_catalog, require_validated,
                                  resolve_documents)
from candidate_evidence import CATALOG_VERSION, profile_digest


ROOT = Path(__file__).resolve().parent

PROFILE = ROOT / "candidate_profile.md"
POSTING = ROOT / "job_posting.txt"

OUTPUT_ROOT = (
    Path.home()
    / "Documents"
    / "JobOps Applications"
)


def validate_documents(documents, profile, posting):
    """Resolve IDs from the same profile snapshot passed to the paid request."""
    if isinstance(documents, ApplicationDocuments):
        require_validated(documents)
        if documents.profile_sha256 != profile_digest(profile):
            raise ValueError("Candidate source snapshot changed. Nothing was exported.")
        return documents
    return resolve_documents(documents, profile, posting)


def write_package(documents, application_url, *, output_root=OUTPUT_ROOT):
    require_validated(documents)
    output_root = Path(output_root).resolve()
    if output_root == ROOT or ROOT in output_root.parents:
        raise ValueError("Application packages must be saved outside the project repository.")
    from word_export import markdown_to_docx
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = output_root / f"{timestamp}_{uuid4().hex[:8]}"
    files = {
        "resume.md": documents.resume_markdown,
        "cover_letter.md": documents.cover_letter_markdown,
        "verification_checklist.md": "# Verify Before Applying\n\n- Review every claim, title, date, credential and metric against your profile.\n- Confirm estimates remain labeled as estimates.\n- Verify the role is still open and check the application URL.\n"
            + "\n".join(f"- {item}" for item in documents.verification_items),
        "application_link.txt": application_url.strip() or "Application URL unavailable; verify before applying.",
        "source_evidence.json": json.dumps({"evidence_format": documents.evidence_format,
            "catalog_version": CATALOG_VERSION, "profile_sha256": documents.profile_sha256,
            "evidence": [e.model_dump() for e in documents.evidence]}, indent=2),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    # Publish the new directory only after both Word exports succeed. A failed
    # export removes only this private staging directory, never existing packages.
    with tempfile.TemporaryDirectory(prefix=".jobops-", dir=output_root) as temporary:
        staging = Path(temporary) / "package"
        staging.mkdir()
        for filename, content in files.items():
            (staging / filename).write_text(content.strip() + "\n", encoding="utf-8")
        markdown_to_docx(documents.resume_markdown, staging / "Resume.docx")
        markdown_to_docx(documents.cover_letter_markdown, staging / "Cover_Letter.docx")
        staging.rename(output)
    return output


def generate_package(profile, posting, application_url="", *, approved=False, output_root=OUTPUT_ROOT):
    if not approved:
        raise PermissionError("Paid document generation requires explicit approval.")
    if not profile.strip() or not posting.strip():
        raise ValueError("Profile or posting is empty.")
    destination = Path(output_root).resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("Application packages must be saved outside the project repository.")
    from ai_runtime import private_run_config
    catalog = document_catalog(profile)
    if not catalog:
        raise ValueError("Candidate profile has no source passages. No paid request was made.")
    try:
        result = Runner.run_sync(application_document_writer,
            json.dumps({"candidate_evidence_catalog": catalog, "catalog_version": CATALOG_VERSION,
                "profile_sha256": profile_digest(profile), "job_posting": posting}, ensure_ascii=False),
            max_turns=1, run_config=private_run_config())
    except ModelBehaviorError:
        raise ValueError("Document response did not match the source-ID selection schema. No documents were exported or retries made. Review the request before approving another attempt.") from None
    documents = validate_documents(result.final_output, profile, posting)
    return write_package(documents, application_url, output_root=destination)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a tailored job application package."
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Enable generation after explicit confirmation.",
    )
    parser.add_argument(
        "--posting-file",
        type=Path,
        default=POSTING,
        help="Path to the selected job posting.",
    )
    parser.add_argument(
        "--application-url",
        default="",
        help="Direct application link to save with documents.",
    )
    args = parser.parse_args()

    if not PROFILE.is_file():
        raise SystemExit("Candidate profile not found.")

    if not args.posting_file.is_file():
        raise SystemExit("Job posting file not found.")

    profile = PROFILE.read_text(encoding="utf-8")
    posting = args.posting_file.read_text(encoding="utf-8")

    if not profile.strip() or not posting.strip():
        raise SystemExit("Profile or job posting is empty.")

    print("\n===== JOBOPS APPLICATION GENERATOR =====")
    print("Candidate profile: Found")
    print("Job posting: Found")
    print("Model: gpt-4.1-mini")
    print("Maximum model turns: 1")

    if not args.generate:
        print("\nDRY RUN PASSED.")
        print("No API calls made.")
        print("Use --generate when ready to create documents.")
        return

    print("\nGeneration uses the paid OpenAI API.")
    print("Review job_posting.txt before proceeding.")

    confirmation = input(
        "Type GENERATE to approve this API call: "
    ).strip()

    if confirmation != "GENERATE":
        print("Cancelled. No API call made.")
        return

    output = generate_package(profile, posting, args.application_url, approved=True)

    print("\n===== DOCUMENTS CREATED =====")
    print("Folder:", output)

    for file in output.iterdir():
        print("-", file.name)

    print("\nReview all documents before applying.")


if __name__ == "__main__":
    main()
