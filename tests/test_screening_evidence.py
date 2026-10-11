"""Source-grounded evidence using fictional profiles and blocked model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.agent_output import AgentOutputSchema
from jobops_service import screen_selected
from jobops_store import JobOpsStore
from qualification_agent import (QualificationBatch, QualificationResult, Requirement,
                                 cache_key, dry_screen, screen_batch, validate_result)
from screening_errors import BatchScreeningError
from test_mvp import fixture, PROFILE, MOTIVE, ENGINE, wire_batch
from candidate_evidence import build_evidence_catalog, profile_digest


class ScreeningEvidenceTests(unittest.TestCase):
    def setUp(self):
        runner = patch('agents.Runner.run_sync', side_effect=AssertionError('Paid requests forbidden'))
        self.runner = runner.start()
        self.addCleanup(runner.stop)
        config = patch('ai_runtime.private_run_config', return_value=None)
        config.start()
        self.addCleanup(config.stop)
        self.job = fixture('Required Qualifications:\n- Experience training teams.')

    def assessment(self, quotes=None, status='supported', evidence_status='profile excerpts'):
        return QualificationResult(job_id=self.job['id'], requirements=[Requirement(
            job_quote='Experience training teams.', importance='mandatory', status=status,
            candidate_quotes=['Coordinated onboarding and training.'] if quotes is None else quotes,
            evidence_status=evidence_status, specialized=False, direct_evidence=True,
            explanation='Fictional assessment.')], explanation='Fictional assessment.')

    def test_valid_positive_evidence_from_profile(self):
        result = validate_result(self.assessment(), self.job, PROFILE)
        self.assertEqual(result.classification, 'Plausible Fit')
        self.assertEqual(result.requirements[0].evidence_status, 'profile excerpts')
        self.assertIsNone(result.requirements[0].verification_question)
        self.runner.assert_not_called()

    def test_whitespace_differences_return_actual_source_excerpt(self):
        source = 'Fictional profile.\nCoordinated  onboarding\r\nand\ttraining.\n'
        for quote in ['Coordinated onboarding and training.', '  Coordinated\nonboarding and  training.  ']:
            with self.subTest(quote=quote):
                result = validate_result(self.assessment([quote]), self.job, source)
                self.assertEqual(result.requirements[0].candidate_quotes,
                                 ['Coordinated  onboarding\r\nand\ttraining.'])
                self.assertEqual(result.classification, 'Plausible Fit')

    def test_request_and_validator_use_the_same_unchanged_profile_string(self):
        profile = 'Fictional profile.\r\nCoordinated\tonboarding  and training.\r\n'
        self.runner.side_effect = None
        assessment = self.assessment()
        assessment.requirements[0].candidate_evidence_ids = ['P001']
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[assessment]))
        result = screen_batch([self.job], profile, approved=True)[0]
        self.assertEqual(json.loads(self.runner.call_args.args[1])['candidate_profile_sha256'], profile_digest(profile))
        self.assertEqual(result.requirements[0].candidate_quotes, [build_evidence_catalog(profile)[0]['text']])
        self.assertEqual(result.classification, 'Plausible Fit')

    def test_legacy_evidence_records_remain_readable(self):
        old = self.assessment().model_dump()
        old['requirements'][0].pop('evidence_status')
        old['requirements'][0].pop('verification_question')
        result = validate_result(QualificationResult.model_validate(old), self.job, PROFILE)
        self.assertEqual(result.classification, 'Plausible Fit')
        self.assertEqual(result.requirements[0].evidence_status, 'profile excerpts')

    def test_not_evidenced_is_unknown_with_question_and_no_fabricated_quote(self):
        result = validate_result(self.assessment([], 'unknown', 'not evidenced'), self.job, PROFILE)
        requirement = result.requirements[0]
        self.assertEqual(result.classification, 'Needs Verification')
        self.assertEqual(requirement.candidate_quotes, [])
        self.assertFalse(requirement.direct_evidence)
        self.assertIn('Experience training teams.', requirement.verification_question)
        self.assertNotEqual(requirement.status, 'unsupported')

    def test_legacy_unknown_absence_markers_become_missing_evidence_only(self):
        for marker in ['Not evidenced', 'Not evidenced in profile.', 'Not evidenced in the candidate profile']:
            with self.subTest(marker=marker):
                result = validate_result(self.assessment([marker], 'unknown', None), self.job, PROFILE)
                self.assertEqual(result.requirements[0].candidate_quotes, [])
                self.assertEqual(result.requirements[0].evidence_status, 'not evidenced')
                self.assertEqual(result.classification, 'Needs Verification')
                self.assertTrue(result.requirements[0].verification_question)

    def test_unsupported_positive_evidence_and_paraphrases_rejected(self):
        for quote in ['Led enterprise fintech implementations.', 'Managed onboarding and staff training.',
                      'Coordinated onboarding and training!', 'Not evidenced in profile']:
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                validate_result(self.assessment([quote]), self.job, PROFILE)

    def test_unknown_status_does_not_allow_fabricated_evidence(self):
        with self.assertRaises(ValueError):
            validate_result(self.assessment(['Built a corporate card platform.'], 'unknown'), self.job, PROFILE)

    def test_missing_evidence_cannot_be_positive_or_contradiction(self):
        for status in ['supported', 'partially supported', 'unsupported']:
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate_result(self.assessment([], status, 'not evidenced'), self.job, PROFILE)
        with self.assertRaises(ValueError):
            validate_result(self.assessment([], 'unknown', 'profile excerpts'), self.job, PROFILE)
        with self.assertRaises(ValueError):
            validate_result(self.assessment(status='unknown', evidence_status='not evidenced'), self.job, PROFILE)

    def test_unknown_license_is_not_proven_absence(self):
        job = fixture('Required Qualifications:\n- Professional license required.')
        result = dry_screen(job, PROFILE)
        self.assertEqual(result.classification, 'Needs Verification')
        self.assertEqual(result.requirements[0].status, 'unknown')
        self.assertEqual(result.requirements[0].evidence_status, 'not evidenced')
        self.assertTrue(result.requirements[0].verification_question)

    def test_motive_engine_mocked_structured_assessments_remain_truthful(self):
        jobs = [fixture(MOTIVE, 'Fictional Motive Operations', 'motive'),
                fixture(ENGINE, 'Fictional Engine Implementation', 'engine')]
        output = wire_batch(results=[dry_screen(j, PROFILE) for j in jobs])
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=output)
        results = screen_batch(jobs, PROFILE, approved=True)
        self.assertEqual([r.classification for r in results], ['Likely Mismatch', 'Likely Mismatch'])
        for result in results:
            self.assertTrue(all(r.status == 'unknown' and not r.candidate_quotes for r in result.requirements))
            self.assertTrue(all(r.verification_question for r in result.requirements))
            self.assertIn('not proof of absent credentials', result.explanation)
        agent, request_text = self.runner.call_args.args
        request = json.loads(request_text)
        self.assertEqual(request['candidate_evidence_catalog'], build_evidence_catalog(PROFILE))
        self.assertEqual([j['descriptionPlain'] for j in request['jobs']], [MOTIVE, ENGINE])
        schema = AgentOutputSchema(agent.output_type)
        parsed = schema.validate_json(output.model_dump_json())
        self.assertEqual(parsed.results[0].requirements[0].candidate_evidence_ids, [])
        self.assertIn('NEVER return candidate quotations', agent.instructions)
        self.assertEqual(self.runner.call_count, 1)

    def test_partial_batch_caches_sourced_result_and_retains_history_for_failed_job(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JobOpsStore(Path(temp) / 'evidence.db')
            store.initialize()
            other = fixture(MOTIVE, 'Fictional Invalid Assessment', 'invalid')
            store.upsert_candidates([('Example', j, 'Remote', 'Verify') for j in [self.job, other]])
            old = dry_screen(other, PROFILE).model_dump()
            store.save_screening(other['id'], 'historical', 'ai', old)
            invalid = dry_screen(other, PROFILE)
            invalid.requirements[0].job_quote = 'Invented enterprise leadership.'
            self.runner.side_effect = None
            positive = self.assessment()
            positive.requirements[0].candidate_evidence_ids = ['P001']
            self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=[positive, invalid]))
            with self.assertRaises(BatchScreeningError) as raised:
                screen_selected(store, [self.job, other], PROFILE, paid=True, approved=True)
            self.assertEqual(raised.exception.saved_count, 1)
            self.assertEqual(store.screening(self.job['id'], cache_key(self.job, PROFILE))['mode'], 'ai')
            self.assertIsNone(store.screening(other['id'], cache_key(other, PROFILE)))
            self.assertEqual(len(store.screening_history(other['id'])), 1)
            self.assertNotIn('Invented enterprise', str(raised.exception))
            with self.assertRaises(PermissionError):
                screen_selected(store, [self.job, other], PROFILE, paid=True)
            self.assertEqual(self.runner.call_count, 1)

    def test_job_identity_and_requirement_quotes_stay_strict(self):
        wrong_id = self.assessment()
        wrong_id.job_id = 'wrong'
        with self.assertRaises(ValueError):
            validate_result(wrong_id, self.job, PROFILE)
        wrong_requirement = self.assessment()
        wrong_requirement.requirements[0].job_quote = 'Experience  training teams.'
        with self.assertRaises(ValueError):
            validate_result(wrong_requirement, self.job, PROFILE)


if __name__ == '__main__':
    unittest.main()
