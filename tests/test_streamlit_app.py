"""Exercise actual Streamlit reruns against fictional data and mocked paid responses."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from jobops_store import JobOpsStore
from qualification_agent import cache_key, dry_screen
from qualification_agent import SourceRequirement, SourceQualificationResult, SourceQualificationBatch
from candidate_evidence import build_evidence_catalog
from test_mvp import wire_batch, fixture, PROFILE, ROOT


class DashboardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        profile = self.path / "profile.md"
        profile.write_text(PROFILE, encoding="utf-8")
        self.store = JobOpsStore(self.path / "ui.db")
        self.store.initialize()
        self.job = fixture()
        self.store.upsert_candidates([("Example", self.job, "Preferred - US remote", "Verify")])
        env = patch.dict(os.environ, {"JOBOPS_DB_PATH": str(self.store.path), "JOBOPS_PROFILE_PATH": str(profile)})
        env.start()
        self.addCleanup(env.stop)
        runner = patch("agents.Runner.run_sync", side_effect=AssertionError("Unexpected API call"))
        self.runner = runner.start()
        self.addCleanup(runner.stop)
        self.app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=20).run()

    def button(self, label):
        return next(b for b in self.app.button if b.label == label)

    def checkbox(self, prefix):
        return next(c for c in self.app.checkbox if c.label.startswith(prefix))

    def metric(self, label):
        return next(m for m in self.app.metric if m.label == label).value

    def selectbox(self, label):
        return next(s for s in self.app.selectbox if s.label == label)

    def add_job(self, job, geography="Preferred - US remote"):
        self.store.upsert_candidates([("Example", job, geography, "Verify")])
        self.app.run()

    def select_job(self, job):
        self.app.button(key="select_job_" + job["id"]).click().run()

    def visible_job_ids(self):
        return {b.key.removeprefix("select_job_") for b in self.app.button
                if b.key and b.key.startswith("select_job_")}

    def test_load_filter_preview_feedback_report_and_dismissal(self):
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.metric[0].value, "1")
        self.runner.assert_not_called()
        self.app.multiselect[0].set_value([self.job["id"]]).run()
        self.button("Free local preview / use cache").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.store.screening(self.job["id"])["mode"], "local")
        self.assertEqual(self.metric("AI Screened"), "0")
        self.app.text_area[0].set_value("Corporate-card background is not established.")
        self.button("Save correction").click().run()
        self.button("Suggest Fix").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.store.feedback(self.job["id"])), 1)
        self.assertGreaterEqual(len(self.app.get("download_button")), 2)
        self.button("Request reevaluation").click().run()
        self.assertTrue(self.store.jobs()[0]["reevaluate"])
        self.button("Dismiss opportunity").click().run()
        self.assertEqual(self.store.jobs()[0]["status"], "Dismissed")
        next(s for s in self.app.selectbox if s.label == "Opportunity status").set_value("All").run()
        self.button("Restore opportunity").click().run()
        self.assertEqual(self.store.jobs()[0]["status"], "Active")
        self.runner.assert_not_called()

    def test_screening_approval_and_no_paid_work_on_rerun(self):
        self.app.multiselect[0].set_value([self.job["id"]]).run()
        self.button("Run approved AI screening").click().run()
        self.assertTrue(self.app.error)
        self.runner.assert_not_called()
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[dry_screen(self.job, PROFILE)]))
        with patch("ai_runtime.private_run_config", return_value=None):
            self.checkbox("I approve paid OpenAI screening").set_value(True)
            self.button("Run approved AI screening").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(self.metric("AI Screened"), "1")
            self.assertEqual(self.runner.call_count, 1)
            self.assertFalse(self.checkbox("I approve paid OpenAI screening").value)
            self.app.run()
            self.assertEqual(self.runner.call_count, 1)
            self.button("Run approved AI screening").click().run()
            self.assertTrue(self.app.error)
            self.assertEqual(self.runner.call_count, 1)

    def test_missing_evidence_and_verification_questions_display_from_cache(self):
        result = dry_screen(self.job, PROFILE).model_dump()
        self.store.save_screening(self.job['id'], cache_key(self.job, PROFILE), 'ai', result)
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(any('Not evidenced in the supplied profile' in c.value for c in self.app.caption))
        self.assertTrue(any(m.value.startswith('Verify: Can you provide profile evidence') for m in self.app.markdown))
        self.runner.assert_not_called()

    def test_source_ids_resolve_in_approved_ui_and_snapshot_survives_profile_edit(self):
        source = build_evidence_catalog(PROFILE)[0]['text']
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=SourceQualificationBatch(results=[
            SourceQualificationResult(job_id=self.job['id'], explanation='Fictional assessment.', requirements=[
                SourceRequirement(job_quote=self.job['descriptionPlain'].splitlines()[1],
                                  importance='mandatory', status='partially supported',
                                  candidate_evidence_ids=['P001'], specialized=True, direct_evidence=False,
                                  explanation='Transferable experience does not establish direct industry evidence.')])]))
        with patch('ai_runtime.private_run_config', return_value=None):
            self.checkbox('I approve paid OpenAI screening').set_value(True)
            self.button('Run approved AI screening').click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any(t.value == 'Candidate evidence (P001): ' + source for t in self.app.text))
        self.assertEqual(self.runner.call_count, 1)
        (self.path / 'profile.md').write_text('A different fictional profile with a different P001 source.', encoding='utf-8')
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any(t.value == 'Candidate evidence (P001): ' + source for t in self.app.text))
        self.assertEqual(self.metric('AI Screened'), '0')
        self.assertEqual(self.runner.call_count, 1)

    def test_invalid_source_ids_display_unknown_warning_and_verification_without_retry(self):
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=SourceQualificationBatch(results=[
            SourceQualificationResult(job_id=self.job['id'], explanation='Unverified claim.', requirements=[
                SourceRequirement(job_quote=self.job['descriptionPlain'].splitlines()[1],
                                  importance='mandatory', status='supported',
                                  candidate_evidence_ids=['P999'], specialized=True, direct_evidence=True,
                                  explanation='Invented accomplishment must not be displayed.')])]))
        with patch('ai_runtime.private_run_config', return_value=None):
            self.checkbox('I approve paid OpenAI screening').set_value(True)
            self.button('Run approved AI screening').click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('downgraded to unknown' in w.value for w in self.app.warning))
        self.assertTrue(any(m.value.startswith('Verify: ') for m in self.app.markdown))
        self.assertTrue(any('Not evidenced in the supplied profile' in c.value for c in self.app.caption))
        self.assertFalse(any('Invented accomplishment' in m.value for m in self.app.markdown))
        self.assertFalse(self.checkbox('I approve paid OpenAI screening').value)
        self.app.run()
        self.button('Run approved AI screening').click().run()
        self.assertEqual(self.runner.call_count, 1)

    def test_legacy_quote_history_displays_without_source_id_fields(self):
        legacy = dry_screen(self.job, PROFILE).model_dump()
        legacy.pop('evidence_format')
        legacy.pop('profile_sha256')
        for requirement in legacy['requirements']:
            requirement.pop('candidate_evidence_ids')
            requirement.pop('evidence_warnings')
            requirement['candidate_quotes'] = ['Coordinated onboarding and training.']
        self.store.save_screening(self.job['id'], 'legacy-quote-format', 'ai', legacy)
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any(t.value == 'Candidate evidence: Coordinated onboarding and training.' for t in self.app.text))
        self.assertEqual(self.metric('AI Screened'), '0')
        self.runner.assert_not_called()

    def test_batch_selection_and_approval_submitted_in_same_rerun(self):
        other = fixture(title="Other Operations Manager", suffix="approval-batch")
        self.add_job(other)
        batch = [self.job["id"], other["id"]]
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(
            results=[dry_screen(self.job, PROFILE), dry_screen(other, PROFILE)],
        ))
        with patch("ai_runtime.private_run_config", return_value=None):
            # The browser can submit pending selection and form values together.
            # Do not render an intermediate page after changing the selection.
            self.app.multiselect[0].set_value(batch)
            self.checkbox("I approve paid OpenAI screening").set_value(True)
            self.button("Run approved AI screening").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertFalse(self.app.error)
        self.assertEqual(self.runner.call_count, 1)
        self.assertEqual(self.metric("AI Screened"), "2")
        request = json.loads(self.runner.call_args.args[1])
        self.assertEqual([j["job_id"] for j in request["jobs"]], batch)
        self.assertFalse(self.checkbox("I approve paid OpenAI screening").value)
        self.app.run()
        self.assertEqual(self.runner.call_count, 1)

    def test_unapproved_batch_submission_is_blocked_even_with_pending_selection(self):
        other = fixture(title="Other Operations Manager", suffix="unapproved-batch")
        self.add_job(other)
        self.app.multiselect[0].set_value([self.job["id"], other["id"]])
        self.button("Run approved AI screening").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual([e.value for e in self.app.error], ["Confirm the paid screening request before proceeding."])
        self.assertFalse(self.store.screening(self.job["id"]))
        self.assertFalse(self.store.screening(other["id"]))
        self.runner.assert_not_called()

    def test_approval_after_batch_selection_rerun_authorizes_the_current_batch(self):
        other = fixture(title="Other Operations Manager", suffix="settled-batch")
        self.add_job(other)
        self.app.multiselect[0].set_value([other["id"]]).run()
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[dry_screen(other, PROFILE)]))
        with patch("ai_runtime.private_run_config", return_value=None):
            self.checkbox("I approve paid OpenAI screening").set_value(True)
            self.button("Run approved AI screening").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertFalse(self.app.error)
        self.assertEqual(self.runner.call_count, 1)
        request = json.loads(self.runner.call_args.args[1])
        self.assertEqual([j["job_id"] for j in request["jobs"]], [other["id"]])
        self.assertFalse(self.store.screening(self.job["id"]))
        self.assertEqual(self.store.screening(other["id"])["mode"], "ai")

    def test_document_generation_requires_approval(self):
        self.button("Generate approved application package").click().run()
        self.assertTrue(self.app.error)
        self.runner.assert_not_called()

    def test_partial_batch_refreshes_metrics_reports_failure_and_consumes_approval(self):
        other = fixture(title="Missing Fictional Opportunity", suffix="partial-batch")
        self.add_job(other)
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[dry_screen(self.job, PROFILE)]))
        with patch("ai_runtime.private_run_config", return_value=None):
            self.app.multiselect[0].set_value([self.job["id"], other["id"]])
            self.checkbox("I approve paid OpenAI screening").set_value(True)
            self.button("Run approved AI screening").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(self.metric("AI Screened"), "1")
            self.assertIn("Missing Fictional Opportunity", self.app.error[0].value)
            self.assertIn("Missing result", self.app.error[0].value)
            self.assertIn("Saved 1", self.app.error[0].value)
            self.assertFalse(self.checkbox("I approve paid OpenAI screening").value)
            self.assertIsNone(self.store.screening(other["id"]))
            self.app.run()
            self.assertEqual(self.runner.call_count, 1)
            self.button("Run approved AI screening").click().run()
            self.assertEqual(self.runner.call_count, 1)
            self.assertTrue(any("Confirm the paid screening request" in e.value for e in self.app.error))

    def test_discovery_requires_click_and_keeps_paid_work_off(self):
        with patch("batch_evaluate.find_candidates", return_value=[("Example", fixture(suffix="2"), "Remote", "Verify")]) as discover:
            self.app.run()
            discover.assert_not_called()
            self.button("Refresh job discovery").click().run()
            self.assertEqual(discover.call_count, 1)
        self.assertEqual(len(self.store.jobs()), 2)
        self.runner.assert_not_called()

    def test_click_updates_details_and_selection_survives_reruns_and_filters(self):
        other = fixture("Required Qualifications:\n- Team training experience.", "Training Operations Lead", "2")
        self.add_job(other)
        self.select_job(other)
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state["selected_job_id"], other["id"])
        self.assertIn(other["title"], [h.value for h in self.app.subheader])
        self.assertIn("- Team training experience.", [t.value for t in self.app.text])
        self.assertEqual(self.app.multiselect[0].value, [other["id"]])
        self.app.run()
        self.assertEqual(self.app.session_state["selected_job_id"], other["id"])
        self.app.text_input(key="job_search").set_value("Implementation Manager").run()
        self.assertEqual(self.visible_job_ids(), {self.job["id"]})
        self.assertEqual(self.app.session_state["selected_job_id"], other["id"])
        self.assertIn(other["title"], [h.value for h in self.app.subheader])
        self.assertTrue(any("outside the current list filters" in c.value for c in self.app.caption))
        self.runner.assert_not_called()

    def test_fixed_height_list_and_four_detail_tabs(self):
        self.assertEqual([tab.label for tab in self.app.tabs], ["Requirements", "AI Assessment", "Feedback", "Application"])
        # Verify the rendering contract, rather than relying on a browser's screen size.
        rendered_blocks = list(self.app.get("flex_container"))
        list_block = next(b for b in rendered_blocks if b.proto.id.endswith("opportunity_list"))
        self.assertEqual(list_block.proto.height_config.pixel_height, 420)

    def test_legacy_geography_keeps_us_remote_and_unknown_locations_visible(self):
        from streamlit_app import outside_default_geography
        self.assertFalse(outside_default_geography({"location": "Remote, United States"}))
        self.assertFalse(outside_default_geography({"location": "Unknown"}))
        self.assertTrue(outside_default_geography({"location": "Toronto, Canada"}))
        self.assertTrue(outside_default_geography({"location": "New York", "workplaceType": "Remote"}))

    def test_compensation_omits_long_ranking_commentary_without_claiming_unknown_is_undisclosed(self):
        from streamlit_app import compensation
        job = dict(self.job, compensation={"summaryComponents": [{"compensationType": "Salary",
            "interval": "1 YEAR", "currencyCode": "USD", "minValue": 130000, "maxValue": 150000}]})
        self.assertEqual(compensation(job), "$130,000 - $150,000/year")
        self.assertEqual(compensation(self.job), "Salary unverified")
        self.assertEqual(compensation(dict(self.job, shouldDisplayCompensationOnJobPostings=False)), "Salary not disclosed")

    def test_switching_jobs_requires_fresh_approval_for_each_action(self):
        other = fixture(title="Other Operations Manager", suffix="2")
        self.add_job(other)
        self.checkbox("I approve paid OpenAI screening").set_value(True)
        self.checkbox("I approve one paid OpenAI document").set_value(True)
        self.app.run()
        self.select_job(other)
        self.assertFalse(self.checkbox("I approve paid OpenAI screening").value)
        self.assertFalse(self.checkbox("I approve one paid OpenAI document").value)
        self.runner.assert_not_called()

    def test_geography_hides_incompatible_history_without_deleting_it(self):
        outside = fixture(title="Canada Operations Manager", suffix="canada")
        outside["location"] = "Toronto, Canada"
        restricted = fixture(title="State Restricted Operations Manager", suffix="restricted")
        unknown = fixture(title="Unverified Remote Operations Manager", suffix="unknown")
        unknown["location"] = "Remote"
        self.add_job(outside, "Outside US - Review eligibility")
        self.add_job(restricted, "Location-restricted remote - Verify")
        self.add_job(unknown, "Remote - Verify US eligibility")
        self.assertEqual(self.visible_job_ids(), {self.job["id"], unknown["id"]})
        self.assertEqual(len(self.store.jobs()), 4)
        hidden = next(j for j in self.store.jobs() if j["id"] == outside["id"])
        self.assertIsNone(hidden["displayed_at"])
        self.checkbox("Show all locations").set_value(True).run()
        self.assertEqual(len(self.visible_job_ids()), 4)
        self.select_job(outside)
        self.checkbox("Show all locations").set_value(False).run()
        self.assertEqual(self.app.session_state["selected_job_id"], outside["id"])
        self.assertEqual(len(self.store.jobs()), 4)
        self.runner.assert_not_called()

    def test_review_stages_and_classification_filters_use_current_ai_only(self):
        other = fixture(title="Screened Operations Manager", suffix="screened")
        self.add_job(other)
        self.store.save_screening(other["id"], cache_key(other, PROFILE), "ai", dry_screen(other, PROFILE).model_dump())
        self.app.run()
        self.assertEqual(self.metric("Discovered"), "2")
        self.assertEqual(self.metric("Unscreened"), "1")
        self.assertEqual(self.metric("AI Screened"), "1")
        self.selectbox("Review stage").set_value("Unscreened").run()
        self.assertEqual(self.visible_job_ids(), {self.job["id"]})
        self.selectbox("Review stage").set_value("AI Screened").run()
        self.assertEqual(self.visible_job_ids(), {other["id"]})
        self.selectbox("Qualification filter").set_value("Likely Mismatch").run()
        self.assertEqual(self.visible_job_ids(), {other["id"]})
        self.selectbox("Qualification filter").set_value("Plausible Fit").run()
        self.assertEqual(self.visible_job_ids(), set())
        self.runner.assert_not_called()

    def test_free_preview_is_useful_but_not_a_confirmed_ai_recommendation(self):
        self.button("Free local preview / use cache").click().run()
        self.assertEqual(self.metric("Unscreened"), "1")
        self.assertEqual(self.metric("AI Screened"), "0")
        self.assertTrue(any("not an AI-screened recommendation" in c.value for c in self.app.caption))
        self.assertTrue(any("corporate card" in t.value for t in self.app.text))
        self.runner.assert_not_called()

    def test_current_cache_preferred_over_newer_stale_result(self):
        valid = dry_screen(self.job, PROFILE).model_dump()
        self.store.save_screening(self.job["id"], cache_key(self.job, PROFILE), "ai", valid)
        self.store.save_screening(self.job["id"], "outdated-key", "local", valid)
        self.app.run()
        self.assertEqual(self.metric("AI Screened"), "1")
        self.assertTrue(any("Current AI assessment" in c.value for c in self.app.caption))
        self.assertFalse(any("Stale assessment" in w.value for w in self.app.warning))
        self.button("Free local preview / use cache").click().run()
        self.runner.assert_not_called()

    def test_stale_ai_results_remain_unscreened_and_inspectable(self):
        self.store.save_screening(self.job["id"], "outdated-key", "ai", dry_screen(self.job, PROFILE).model_dump())
        self.app.run()
        self.assertEqual(self.metric("AI Screened"), "0")
        self.assertEqual(self.metric("Unscreened"), "1")
        self.assertTrue(any("Stale assessment" in w.value for w in self.app.warning))
        self.runner.assert_not_called()

    def test_reject_restore_and_feedback_remain_targeted_after_selection(self):
        other = fixture(title="Other Operations Manager", suffix="2")
        self.add_job(other)
        self.select_job(other)
        self.app.text_area[0].set_value("This requires direct industry experience.")
        self.button("Save correction").click().run()
        self.assertEqual(len(self.store.feedback(other["id"])), 1)
        self.assertFalse(self.store.feedback(self.job["id"]))
        self.button("Reject opportunity").click().run()
        self.assertEqual(self.app.session_state["selected_job_id"], other["id"])
        self.assertEqual(next(j for j in self.store.jobs() if j["id"] == other["id"])["status"], "Rejected")
        self.button("Restore opportunity").click().run()
        self.assertEqual(next(j for j in self.store.jobs() if j["id"] == other["id"])["status"], "Active")
        self.runner.assert_not_called()

    def test_document_approval_and_generation_target_selected_job(self):
        other = fixture("Required Qualifications:\n- Coordinate team training.", "Training Operations Lead", "2")
        self.add_job(other)
        self.select_job(other)
        self.assertFalse(self.checkbox("I approve one paid OpenAI document").value)
        output = self.path / "fictional-package"
        with patch("generate_application.generate_package", return_value=output) as generate:
            self.checkbox("I approve one paid OpenAI document").set_value(True)
            self.button("Generate approved application package").click().run()
            self.assertEqual(len(self.app.exception), 0)
            generate.assert_called_once()
            args, kwargs = generate.call_args
            self.assertEqual(args[0], PROFILE)
            self.assertIn(other["title"], args[1])
            self.assertIn("Coordinate team training", args[1])
            self.assertEqual(args[2], other["applyUrl"])
            self.assertTrue(kwargs["approved"])
            self.assertFalse(self.checkbox("I approve one paid OpenAI document").value)
            self.app.run()
            generate.assert_called_once()
        self.assertEqual(len(self.store.packages(other["id"])), 1)
        self.assertFalse(self.store.packages(self.job["id"]))
        self.assertTrue(any(str(output) in t.value for t in self.app.text))
        self.runner.assert_not_called()

    def test_document_pipeline_failure_then_fresh_approval_exports_valid_package(self):
        from application_documents import DocumentBlock, ResumeSection, SourceApplicationDocuments
        from generate_application import generate_package
        from docx import Document
        valid = SourceApplicationDocuments(resume_sections=[ResumeSection(heading="Experience",
            blocks=[DocumentBlock(evidence_ids=["P001"], phrasing="source")])],
            cover_letter_paragraphs=[DocumentBlock(evidence_ids=["P001"], phrasing="source")],
            verification_items=["Verify dates before submission."])
        invalid = valid.model_copy(deep=True)
        invalid.cover_letter_paragraphs[0].evidence_ids = ["P999"]
        self.runner.side_effect = [SimpleNamespace(final_output=invalid), SimpleNamespace(final_output=valid)]
        output = self.path / "application-packages"

        def generate_locally(*args, **kwargs):
            return generate_package(*args, **kwargs, output_root=output)

        with patch("generate_application.generate_package", side_effect=generate_locally), patch("ai_runtime.private_run_config", return_value=None):
            self.checkbox("I approve one paid OpenAI document").set_value(True)
            self.button("Generate approved application package").click().run()
            self.assertTrue(any("unrecognized candidate evidence ID" in e.value for e in self.app.error))
            self.assertFalse(self.store.packages(self.job["id"]))
            self.assertFalse(output.exists())
            self.assertFalse(self.checkbox("I approve one paid OpenAI document").value)
            self.app.run()
            self.assertEqual(self.runner.call_count, 1)
            self.button("Generate approved application package").click().run()
            self.assertTrue(any("explicit approval" in e.value for e in self.app.error))
            self.assertEqual(self.runner.call_count, 1)
            self.checkbox("I approve one paid OpenAI document").set_value(True)
            self.button("Generate approved application package").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(self.runner.call_count, 2)
            self.assertFalse(self.checkbox("I approve one paid OpenAI document").value)
            packages = self.store.packages(self.job["id"])
            self.assertEqual(len(packages), 1)
            folder = Path(packages[0]["folder"])
            self.assertIn("Coordinated onboarding", " ".join(p.text for p in Document(folder / "Resume.docx").paragraphs))
            self.assertTrue((folder / "Cover_Letter.docx").is_file())
            self.app.run()
            self.assertEqual(self.runner.call_count, 2)


if __name__ == "__main__":
    unittest.main()
