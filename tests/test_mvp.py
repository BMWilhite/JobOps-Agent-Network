import json
import os
import runpy
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from application_documents import SourceApplicationDocuments, ResumeSection, DocumentBlock
from generate_application import ROOT, generate_package, validate_documents, write_package
from jobops_service import screen_selected
from jobops_store import JobOpsStore, stable_job_id
from qualification_agent import (Requirement, QualificationResult,
                                 cache_key, classify, dry_screen, screen_batch, validate_result)
from qualification_agent import SourceRequirement, SourceQualificationResult, SourceQualificationBatch

PROFILE = """Fictional candidate. Owner of a small service business.
Implementation Manager for a content service, 2021-2023.
Coordinated onboarding and training. Moderate spreadsheet experience.
No investment banking background. Beginner SQL.
"""
MOTIVE = """Required Qualifications:
- 5+ years combining consulting or investment banking and SaaS experience.
- Recent hypergrowth SaaS experience.
- Expert spreadsheet and data modeling skills.
"""
ENGINE = """Required Qualifications:
- 6+ years implementing solutions in corporate cards, spend management, or B2B fintech.
- End-to-end corporate card implementations.
- Specialized financial-system integrations.
- Corporate card industry background.
"""


def fixture(description=ENGINE, title="Implementation Manager", suffix="1"):
    job = {"title": title, "descriptionPlain": description, "location": "Remote, United States",
           "jobUrl": "https://jobs.example.test/roles/" + suffix,
           "applyUrl": "https://jobs.example.test/roles/" + suffix + "/application"}
    return dict(job, id=stable_job_id("Example", job), company="Example", status="Active", reevaluate=False)


def wire_batch(results):
    """Mock the actual ID-only provider contract, not persisted result snapshots."""
    return SourceQualificationBatch(results=[SourceQualificationResult(
        job_id=result.job_id, explanation=result.explanation,
        requirements=[SourceRequirement(
            job_quote=r.job_quote, importance=r.importance, status=r.status,
            candidate_evidence_ids=r.candidate_evidence_ids or [], specialized=r.specialized,
            direct_evidence=r.direct_evidence, explanation=r.explanation,
        ) for r in result.requirements],
    ) for result in results])


class MVPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobOpsStore(Path(self.temp.name) / "test.db")
        self.store.initialize()
        self.job = fixture()
        self.store.upsert_candidates([("Example", self.job, "Preferred - US remote", "Verify")])
        self.network = patch("agents.Runner.run_sync", side_effect=AssertionError("Unapproved API call"))
        self.runner = self.network.start()
        self.addCleanup(self.network.stop)

    def test_motive_and_engine_specialized_regressions(self):
        for title, description in [("Motive: Business Operations Manager", MOTIVE),
                                   ("Engine: Sr. Manager, Implementation - Engine X", ENGINE)]:
            result = dry_screen(fixture(description, title), PROFILE)
            self.assertEqual(result.classification, "Likely Mismatch", title)
            self.assertTrue(all(r.status == "unknown" for r in result.requirements))
            self.assertTrue(all(r.job_quote in description for r in result.requirements))
        self.runner.assert_not_called()

    def test_preferred_specializations_do_not_block(self):
        job = fixture("Required Qualifications:\n- Experience training teams.\nPreferred Qualifications:\n- Hypergrowth SaaS experience.\n- Corporate card industry background.")
        result = dry_screen(job, PROFILE)
        result.requirements[0].status = "supported"
        result.requirements[0].candidate_quotes = ["Coordinated onboarding and training."]
        self.assertEqual(classify(result.requirements), "Plausible Fit")
        self.assertEqual([r.importance for r in result.requirements[1:]], ["preferred", "preferred"])

    def test_unknown_credential_is_not_absence(self):
        result = dry_screen(fixture("Required Qualifications:\n- Professional license required."), PROFILE)
        self.assertEqual(result.classification, "Needs Verification")
        self.assertEqual(result.requirements[0].status, "unknown")

    def test_explicit_unsupported_mandatory_mismatch(self):
        r = Requirement(job_quote="Investment banking experience required.", importance="mandatory",
                        status="unsupported", candidate_quotes=["No investment banking background."],
                        specialized=True, direct_evidence=False, explanation="Explicit contradiction.")
        job = fixture(r.job_quote)
        result = validate_result(QualificationResult(job_id=job["id"], requirements=[r], explanation="Mismatch"), job, PROFILE)
        self.assertEqual(result.classification, "Likely Mismatch")

    def test_transferable_is_not_direct(self):
        job = fixture("Required Qualifications:\n- Corporate card implementation experience.")
        r = dry_screen(job, PROFILE)
        r.requirements[0].status = "supported"
        r.requirements[0].candidate_quotes = ["Coordinated onboarding and training."]
        r.requirements[0].evidence_status = "profile excerpts"
        self.assertEqual(validate_result(r, job, PROFILE).classification, "Needs Verification")
        self.assertEqual(r.requirements[0].status, "partially supported")

    def test_generic_onboarding_cannot_be_mislabeled_as_direct_card_experience(self):
        job = fixture("Required Qualifications:\n- Corporate card implementation experience.")
        result = dry_screen(job, PROFILE)
        result.requirements[0].status = "supported"
        result.requirements[0].specialized = False
        result.requirements[0].direct_evidence = True
        result.requirements[0].candidate_quotes = ["Coordinated onboarding and training."]
        result.requirements[0].evidence_status = "profile excerpts"
        validated = validate_result(result, job, PROFILE)
        self.assertEqual(validated.classification, "Needs Verification")
        self.assertFalse(validated.requirements[0].direct_evidence)

    def test_greenhouse_query_job_ids_do_not_collide(self):
        from job_discovery import normalize_posting_url
        self.assertNotEqual(normalize_posting_url("https://example.test/careers?gh_jid=123&utm_source=x"),
                            normalize_posting_url("https://example.test/careers?gh_jid=456"))
        self.assertEqual(normalize_posting_url("https://example.test/careers?gh_jid=123&utm_source=x"),
                         normalize_posting_url("https://example.test/careers?gh_jid=123"))

    def test_fabricated_citations_rejected(self):
        r = dry_screen(self.job, PROFILE)
        r.requirements[0].candidate_quotes = ["Invented fintech accomplishment"]
        with self.assertRaises(ValueError):
            validate_result(r, self.job, PROFILE)

    def test_paid_gates_and_free_preview(self):
        with self.assertRaises(PermissionError):
            screen_batch([self.job], PROFILE)
        with self.assertRaises(PermissionError):
            screen_selected(self.store, [self.job], PROFILE, paid=True)
        with self.assertRaises(PermissionError):
            generate_package(PROFILE, ENGINE)
        results, calls = screen_selected(self.store, [self.job], PROFILE)
        self.assertEqual(calls, 0)
        self.assertEqual(results[0]["classification"], "Likely Mismatch")
        self.runner.assert_not_called()

    def test_standalone_agent_clis_require_confirmation(self):
        for name in ["extraction_agent.py", "fit_analyst.py", "skeptical_reviewer.py", "application_strategist.py"]:
            with self.subTest(name=name), patch("builtins.input", return_value=""), self.assertRaises(SystemExit):
                runpy.run_path(str(ROOT / name), run_name="__main__")
        self.runner.assert_not_called()

    def test_approved_ai_batch_and_cache(self):
        other = fixture(MOTIVE, "Operations Manager", "2")
        self.store.upsert_candidates([("Example", other, "Remote", "Verify")])
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[dry_screen(self.job, PROFILE), dry_screen(other, PROFILE)]))
        with patch("ai_runtime.private_run_config", return_value=None):
            results, calls = screen_selected(self.store, [self.job, other], PROFILE, paid=True, approved=True)
            self.assertEqual(len(results), 2)
            self.assertEqual(calls, 1)
            self.assertEqual(self.runner.call_count, 1)
            _, calls = screen_selected(self.store, [self.job, other], PROFILE, paid=True, approved=True)
            self.assertEqual(calls, 0)
            self.assertEqual(self.runner.call_count, 1)
        for job in [self.job, other]:
            self.assertEqual(self.store.screening(job["id"], cache_key(job, PROFILE))["mode"], "ai")

    def test_cache_invalidation_and_requested_reevaluation(self):
        original = dry_screen(self.job, PROFILE).model_dump()
        self.store.save_screening(self.job["id"], cache_key(self.job, PROFILE), "ai", original)
        self.assertIsNone(self.store.screening(self.job["id"], cache_key(self.job, PROFILE + "Updated.")))
        changed = dict(self.job, descriptionPlain=ENGINE + "Another requirement.")
        self.assertNotEqual(cache_key(changed, PROFILE), cache_key(self.job, PROFILE))
        self.store.request_reevaluation(self.job["id"])
        self.assertTrue(self.store.jobs()[0]["reevaluate"])
        # Requesting reevaluation itself is free and leaves the original assessment intact.
        self.runner.assert_not_called()
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[dry_screen(self.job, PROFILE)]))
        with patch("ai_runtime.private_run_config", return_value=None):
            screen_selected(self.store, self.store.jobs(), PROFILE, paid=True, approved=True)
        self.assertEqual(len(self.store.screening_history(self.job["id"])), 2)
        self.assertFalse(self.store.jobs()[0]["reevaluate"])

    def test_bad_batch_is_not_partially_cached(self):
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[]))
        with patch("ai_runtime.private_run_config", return_value=None), self.assertRaises(ValueError):
            screen_selected(self.store, [self.job], PROFILE, paid=True, approved=True)
        self.assertIsNone(self.store.screening(self.job["id"]))

    def test_dedup_discovery_display_and_disposition(self):
        duplicate = dict(self.job, jobUrl=self.job["jobUrl"] + "?utm_source=test")
        self.assertEqual(stable_job_id("Example", duplicate), self.job["id"])
        self.store.upsert_candidates([("Example", duplicate, "Remote", "Verify")])
        self.assertEqual(len(self.store.jobs()), 1)
        self.assertIsNone(self.store.jobs()[0]["displayed_at"])
        self.store.set_status(self.job["id"], "Rejected")
        self.store.upsert_candidates([("Example", self.job, "Remote", "Verify")])
        self.assertEqual(self.store.jobs()[0]["status"], "Rejected")
        self.store.mark_displayed(self.job["id"])
        self.assertIsNotNone(self.store.jobs()[0]["displayed_at"])
        self.store.set_status(self.job["id"], "Active")
        self.assertEqual(self.store.jobs()[0]["status"], "Active")

    def test_feedback_snapshot_survives_reevaluation(self):
        screen_selected(self.store, [self.job], PROFILE)
        old = self.store.screening(self.job["id"])
        self.store.add_feedback(self.job, old, "Requires direct corporate card background.", "Likely Mismatch")
        self.store.save_screening(self.job["id"], "new-version", "local", {"classification": "Needs Verification"})
        feedback = self.store.feedback(self.job["id"])[0]
        self.assertEqual(feedback["snapshot"]["original_screening"], old)
        self.assertEqual(feedback["report"]["original_classification"], "Likely Mismatch")
        self.assertFalse(feedback["report"]["proposed_generalizable_improvement"]["code_changed"])
        self.assertIn("regression_case_draft", feedback["report"])
        self.runner.assert_not_called()

    def test_legacy_tables_and_evaluations_preserved(self):
        path = Path(self.temp.name) / "legacy.db"
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript("CREATE TABLE jobs(id INTEGER PRIMARY KEY, company TEXT, title TEXT, url TEXT, description TEXT); CREATE TABLE evaluations(id INTEGER PRIMARY KEY, job_id INTEGER, recommendation TEXT);")
            conn.execute("INSERT INTO jobs VALUES(1,'Fictional','Operations Manager','https://jobs.example.test/legacy','Original description')")
            conn.execute("INSERT INTO evaluations VALUES(1,1,'Hold')")
            before = conn.execute("SELECT * FROM jobs").fetchall(), conn.execute("SELECT * FROM evaluations").fetchall()
        store = JobOpsStore(path)
        store.initialize()
        store.initialize()
        with closing(sqlite3.connect(path)) as conn:
            after = conn.execute("SELECT * FROM jobs").fetchall(), conn.execute("SELECT * FROM evaluations").fetchall()
        self.assertEqual(before, after)
        self.assertEqual(len(store.jobs()), 1)
        self.assertEqual(store.jobs()[0]["legacy_evaluation"]["recommendation"], "Hold")

    def test_unavailable_boards_keep_prior_jobs_and_specialized_jobs(self):
        from batch_evaluate import find_candidates
        notices = []
        with patch("batch_evaluate.fetch_ashby_jobs", side_effect=OSError("Unavailable")), patch("batch_evaluate.fetch_greenhouse_jobs", return_value=[{
                "id": 50, "title": "Business Operations Manager", "absolute_url": "https://jobs.example.test/new",
                "location": {"name": "Remote, United States"}, "content": "<h2>Required Qualifications:</h2><p>Recent hypergrowth SaaS experience.</p><p>Expert spreadsheet and data modeling skills.</p>"}]):
            candidates = find_candidates(include_tracked=True, include_filtered=True, warnings=notices)
        self.assertTrue(notices)
        self.assertTrue(candidates)
        self.store.upsert_candidates(candidates)
        self.assertIn(self.job["id"], {j["id"] for j in self.store.jobs()})
        self.runner.assert_not_called()

    def documents(self):
        block = DocumentBlock(evidence_ids=["P001"], phrasing="source")
        return SourceApplicationDocuments(resume_sections=[ResumeSection(heading="Experience", blocks=[block])],
            cover_letter_paragraphs=[block], verification_items=["Verify dates."])

    def test_real_word_package_and_numeric_guard(self):
        from docx import Document
        docs = validate_documents(self.documents(), PROFILE, ENGINE)
        package = write_package(docs, self.job["applyUrl"], output_root=Path(self.temp.name) / "packages")
        self.assertEqual({p.name for p in package.iterdir()}, {"resume.md", "cover_letter.md", "verification_checklist.md", "application_link.txt", "source_evidence.json", "Resume.docx", "Cover_Letter.docx"})
        self.assertIn("Coordinated onboarding", " ".join(p.text for p in Document(package / "Resume.docx").paragraphs))
        docs.resume_markdown += "\n- Saved $999999 annually."
        with self.assertRaises(ValueError):
            validate_documents(docs, PROFILE, ENGINE)
        self.runner.assert_not_called()

    def test_generation_guard_precedes_paid_call(self):
        with self.assertRaises(ValueError):
            generate_package(PROFILE, ENGINE, approved=True, output_root=ROOT / "applications")
        self.runner.assert_not_called()

    def test_approved_generation_uses_existing_writer(self):
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=self.documents())
        with patch("ai_runtime.private_run_config", return_value=None):
            folder = generate_package(PROFILE, ENGINE, self.job["applyUrl"], approved=True, output_root=Path(self.temp.name) / "drafts")
        self.assertTrue((folder / "Resume.docx").is_file())
        self.assertEqual(self.runner.call_count, 1)

    def test_orchestrator_strategy_regression_without_api(self):
        import orchestrator
        example = json.loads((ROOT / "example_evaluation.json").read_text(encoding="utf-8"))
        from extraction_agent import ExtractedJob
        from fit_analyst import FitAssessment
        from skeptical_reviewer import ReviewResult
        from application_strategist import ApplicationPlan
        profile = Path(self.temp.name) / "profile.md"
        profile.write_text(PROFILE, encoding="utf-8")
        with self.assertRaises(PermissionError):
            orchestrator.evaluate_job(ENGINE, profile)
        self.runner.side_effect = [SimpleNamespace(final_output=model.model_validate(example[key])) for model, key in [
            (ExtractedJob, "job"), (FitAssessment, "initial_assessment"),
            (ReviewResult, "review"), (ApplicationPlan, "strategy")]]
        with patch("orchestrator.private_run_config", return_value=None):
            result = orchestrator.evaluate_job(ENGINE, profile, approved=True)
        self.assertIn(result["recommendation"], ["Apply", "Hold", "Skip"])
        self.assertEqual(self.runner.call_count, 4)


if __name__ == "__main__":
    unittest.main()
