"""Offline document contract/export tests; all candidate data is fictional."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docx import Document
from pydantic import ValidationError
from agents.exceptions import ModelBehaviorError
from agents.agent_output import AgentOutputSchema

from application_documents import (DocumentBlock, ResumeSection,
                                   SourceApplicationDocuments, application_document_writer)
from application_evidence import document_catalog
from candidate_evidence import build_evidence_catalog, profile_digest
from generate_application import generate_package, validate_documents, write_package


PROFILE = """# Fictional profile
## Contact
- Avery Example, avery@example.test.
## Target Roles
- Business Operations & Systems. Strategy & Operations.
## Employment
- Implementation Coordinator at Example Services, 2021-2023.
- Coordinated onboarding and\n  training for 12 employees. Results are estimated, not independently verified.
## Skills
- Beginner SQL; moderate Excel; AI-assisted drafting. No fintech or SaaS industry experience.
## Education
- BA in History, Example College, 2020.
"""
POSTING = """Stedi — Business Operations & Systems.
Required: advanced SQL, fintech experience, integrations, SaaS and expert Excel.
Ownership of business systems and measurable process improvements.
"""


def block(*ids, phrasing="source"):
    return DocumentBlock(evidence_ids=list(ids), phrasing=phrasing)


def draft():
    return SourceApplicationDocuments(resume_sections=[
        ResumeSection(heading="Contact", blocks=[block("P001")]),
        ResumeSection(heading="Experience", blocks=[block("P003"), block("P004")]),
        ResumeSection(heading="Skills", blocks=[block("P005")]),
        ResumeSection(heading="Education", blocks=[block("P006")]),
    ], cover_letter_paragraphs=[block("P004", phrasing="first_person"), block("P005")],
        verification_items=["Verify whether additional integrations experience is documented."])


class ApplicationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "packages"
        runner = patch("agents.Runner.run_sync", side_effect=AssertionError("Unexpected paid API call"))
        self.runner = runner.start()
        self.addCleanup(runner.stop)

    def resolve(self, value=None):
        return validate_documents(value or draft(), PROFILE, POSTING)

    def test_shared_catalog_and_exact_resolved_source(self):
        self.assertEqual([{k: v for k, v in e.items() if k != 'content_units'} for e in document_catalog(PROFILE)], build_evidence_catalog(PROFILE))
        docs = self.resolve()
        catalog = {e["evidence_id"]: e["text"] for e in build_evidence_catalog(PROFILE)}
        for evidence in docs.evidence:
            if evidence.source == 'job_posting':
                self.assertEqual(evidence.source_quote, POSTING)
                continue
            self.assertEqual(evidence.source_quote, catalog[evidence.evidence_id])
            self.assertIn(evidence.claim, getattr(docs, evidence.document + "_markdown"))
            self.assertEqual(evidence.source, "candidate_profile")
        self.assertEqual(docs.profile_sha256, profile_digest(PROFILE))
        self.runner.assert_not_called()

    def test_sourced_paraphrase_whitespace_and_qualifiers(self):
        docs = self.resolve()
        self.assertIn("I coordinated onboarding and training for 12 employees (estimated).", docs.cover_letter_markdown)
        self.assertNotIn("not independently verified", docs.cover_letter_markdown)
        self.assertIn("Beginner SQL", docs.resume_markdown)
        self.assertIn("moderate Excel", docs.resume_markdown)
        self.assertIn("AI-assisted", docs.resume_markdown)
        self.assertNotIn("No fintech or SaaS industry experience", docs.cover_letter_markdown)
        self.assertNotIn("advanced SQL", docs.resume_markdown)
        self.assertNotIn("expert Excel", docs.cover_letter_markdown)

    def test_multiple_ids(self):
        value = draft()
        value.cover_letter_paragraphs = [block("P003", "P004")]
        docs = self.resolve(value)
        citations = [e for e in docs.evidence if e.document == "cover_letter" and e.source_unit_index is not None]
        self.assertEqual([e.evidence_id for e in citations], ["P003", "P004"])

    def test_fabricated_achievements_and_metrics_cannot_enter_wire_schema(self):
        for field, text in [("text", "Owned a fintech SaaS company."),
                            ("claim", "Reduced costs by $999999."),
                            ("source_quote", "Expert SQL and Excel.")]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                DocumentBlock.model_validate({"evidence_ids": ["P004"], "phrasing": "source", field: text})
        payload = draft().model_dump()
        payload["resume_markdown"] = "Managed 999999 employees."
        with self.assertRaises(ValidationError):
            SourceApplicationDocuments.model_validate(payload)

    def test_fabricated_ids_and_job_citations_rejected_privately(self):
        for evidence_id in ["P999", "J001", "p004", " candidate secret "]:
            value = draft()
            value.cover_letter_paragraphs = [block(evidence_id)]
            with self.subTest(evidence_id=evidence_id), self.assertRaises(ValueError) as caught:
                self.resolve(value)
            message = str(caught.exception)
            self.assertIn("cover_letter block 1", message)
            self.assertNotIn(evidence_id, message)
            self.assertNotIn("avery@", message)

    def test_aspiration_cannot_become_employment_or_cover_letter_experience(self):
        for document in ["resume", "cover_letter"]:
            value = draft()
            if document == "resume":
                value.resume_sections[1].blocks = [block("P002")]
            else:
                value.cover_letter_paragraphs = [block("P002", phrasing="first_person")]
            with self.subTest(document=document), self.assertRaisesRegex(ValueError, "aspiration"):
                self.resolve(value)

    def test_skills_cannot_be_promoted_to_job_or_credential(self):
        for heading in ["Experience", "Achievements", "Education", "Certifications"]:
            value = draft()
            value.resume_sections = [ResumeSection(heading=heading, blocks=[block("P005")])]
            with self.subTest(heading=heading), self.assertRaises(ValueError):
                self.resolve(value)

    def test_missing_and_duplicate_evidence_rejected(self):
        for ids in [[], ["P004", "P004"]]:
            value = draft()
            value.cover_letter_paragraphs = [block(*ids)]
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.resolve(value)

    def test_complete_generation_exports_editable_docx_and_versioned_provenance(self):
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=draft())
        with patch("ai_runtime.private_run_config", return_value=None):
            folder = generate_package(PROFILE, POSTING, "https://example.test/apply", approved=True, output_root=self.output)
        self.assertEqual(self.runner.call_count, 1)
        request = json.loads(self.runner.call_args.args[1])
        self.assertEqual(request["candidate_evidence_catalog"], document_catalog(PROFILE))
        self.assertEqual(request["profile_sha256"], profile_digest(PROFILE))
        self.assertEqual(request["job_posting"], POSTING)
        self.assertNotIn("candidate_profile", request)
        self.assertEqual(self.runner.call_args.kwargs["max_turns"], 1)
        self.assertIs(application_document_writer.output_type, SourceApplicationDocuments)
        for filename in ["Resume.docx", "Cover_Letter.docx"]:
            word = Document(folder / filename)
            text = " ".join(p.text for p in word.paragraphs)
            self.assertIn("12 employees", text)
            self.assertIn("estimated", text)
            self.assertNotIn("P004", text)
            self.assertTrue(word.part.package.parts)
        citations = json.loads((folder / "source_evidence.json").read_text())
        self.assertEqual(citations["evidence_format"], "application-source-ids-v2-quality")
        self.assertEqual(citations["profile_sha256"], profile_digest(PROFILE))
        self.assertTrue((folder / "verification_checklist.md").is_file())
        self.assertEqual((folder / "application_link.txt").read_text().strip(), "https://example.test/apply")

    def test_invalid_response_does_not_write_or_retry(self):
        value = draft()
        value.cover_letter_paragraphs = [block("P999")]
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=value)
        with patch("ai_runtime.private_run_config", return_value=None), self.assertRaisesRegex(ValueError, "Nothing was exported"):
            generate_package(PROFILE, POSTING, approved=True, output_root=self.output)
        self.runner.assert_called_once()
        self.assertFalse(self.output.exists())
        with self.assertRaises(PermissionError):
            generate_package(PROFILE, POSTING, output_root=self.output)
        self.runner.assert_called_once()

    def test_approval_required_before_every_call(self):
        with self.assertRaises(PermissionError):
            generate_package(PROFILE, POSTING, output_root=self.output)
        self.runner.assert_not_called()

    def test_changed_narrative_cannot_export_even_if_number_is_elsewhere_in_profile(self):
        for document in ["resume", "cover_letter"]:
            docs = self.resolve()
            setattr(docs, document + "_markdown", "Managed 12 fintech businesses.")
            with self.subTest(document=document), self.assertRaises(ValueError):
                write_package(docs, "", output_root=self.output)
        self.assertFalse(self.output.exists())

    def test_changed_profile_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            validate_documents(self.resolve(), PROFILE + "\nNew source", POSTING)

    def test_word_export_failure_does_not_publish_partial_package_or_change_existing(self):
        from word_export import markdown_to_docx
        self.output.mkdir()
        sentinel = self.output / "existing-resume.docx"
        sentinel.write_bytes(b"existing output")
        def export_then_fail(markdown, destination):
            if destination.name == "Cover_Letter.docx":
                raise OSError("Fictional export failure")
            markdown_to_docx(markdown, destination)

        with patch("word_export.markdown_to_docx", side_effect=export_then_fail), self.assertRaises(OSError):
            write_package(self.resolve(), "", output_root=self.output)
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"existing output")

    def test_legacy_free_text_response_is_not_accepted_as_new_evidence(self):
        old = SimpleNamespace(resume_markdown="Invented claim", evidence=[])
        with self.assertRaisesRegex(ValueError, "unsupported response format"):
            self.resolve(old)

    def test_sdk_schema_and_invalid_output_diagnostic_are_private(self):
        self.assertTrue(AgentOutputSchema(SourceApplicationDocuments).is_strict_json_schema())
        self.runner.side_effect = ModelBehaviorError("Private fictional candidate text and secret token")
        with patch("ai_runtime.private_run_config", return_value=None), self.assertRaises(ValueError) as caught:
            generate_package(PROFILE, POSTING, approved=True, output_root=self.output)
        self.assertIn("source-ID selection schema", str(caught.exception))
        self.assertNotIn("Private fictional", str(caught.exception))
        self.assertNotIn("secret token", str(caught.exception))
        self.runner.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_source_employer_role_and_dates_in_heading_are_preserved(self):
        profile = "## Employment\n### Example Services — Implementation Coordinator, 2021-2023\n- Coordinated onboarding and training.\n"
        value = SourceApplicationDocuments(resume_sections=[ResumeSection(heading="Experience", blocks=[block("P001")])],
            cover_letter_paragraphs=[block("P001", phrasing="first_person")], verification_items=[])
        docs = validate_documents(value, profile, POSTING)
        self.assertIn("### Example Services", docs.resume_markdown)
        self.assertIn("Implementation Coordinator | 2021-2023", docs.resume_markdown)
        self.assertEqual(docs.evidence[0].source_context, "Example Services — Implementation Coordinator, 2021-2023")

    def test_unheaded_career_aspirations_are_not_experience(self):
        profile = "I want to become a Business Operations manager.\n"
        value = SourceApplicationDocuments(resume_sections=[ResumeSection(heading="Experience", blocks=[block("P001")])],
            cover_letter_paragraphs=[block("P001")], verification_items=[])
        with self.assertRaisesRegex(ValueError, "aspiration"):
            validate_documents(value, profile, POSTING)

    def test_passive_sentence_does_not_make_candidate_its_actor(self):
        value = SourceApplicationDocuments(resume_sections=[ResumeSection(heading="Experience", blocks=[block("P001")])],
            cover_letter_paragraphs=[block("P001", phrasing="first_person")], verification_items=[])
        for passage in ["Managed by the implementation director.", "Implemented at Example by another team."]:
            profile = "## Employment\n- " + passage + "\n"
            with self.subTest(passage=passage):
                docs = validate_documents(value, profile, POSTING)
                self.assertIn(passage, docs.cover_letter_markdown)
                self.assertNotIn("I managed", docs.cover_letter_markdown)
                self.assertNotIn("I implemented", docs.cover_letter_markdown)


if __name__ == "__main__":
    unittest.main()
