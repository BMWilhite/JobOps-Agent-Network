"""Exercise the real ID-only model contract with sanitized profiles and no network."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.agent_output import AgentOutputSchema
from candidate_evidence import build_evidence_catalog, profile_digest
from jobops_service import screen_selected
from jobops_store import JobOpsStore
from qualification_agent import (SourceRequirement, SourceQualificationResult, SourceQualificationBatch,
                                 QualificationBatch, cache_key, dry_screen, screen_batch, validate_result)
from screening_errors import BatchScreeningError
from test_mvp import fixture, MOTIVE, ENGINE

PROFILE = ('# Fictional candidate\r\n\r\n'
           'Operated a small service business.\r\n\r\n'
           '## Implementation experience\r\n'
           '- Coordinated onboarding and training.\r\n'
           '  Managed service delivery for content teams.\r\n'
           '- Managed scheduling and customer communication.\r\n\r\n'
           'Moderate spreadsheet experience; beginner SQL.\r\n')


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = JobOpsStore(Path(temp.name) / 'source.db')
        self.store.initialize()
        self.job = fixture('Required Qualifications:\n- Experience training teams.')
        self.store.upsert_candidates([('Example', self.job, 'Remote', 'Verify')])
        runner = patch('agents.Runner.run_sync', side_effect=AssertionError('No real model calls'))
        self.runner = runner.start()
        self.addCleanup(runner.stop)
        config = patch('ai_runtime.private_run_config', return_value=None)
        config.start()
        self.addCleanup(config.stop)

    def assessment(self, ids=None, status='supported', job=None, specialized=False):
        job = job or self.job
        return SourceQualificationResult(job_id=job['id'], explanation='Fictional assessment.', requirements=[
            SourceRequirement(job_quote=job['descriptionPlain'].splitlines()[-1],
                              importance='mandatory', status=status,
                              candidate_evidence_ids=['P002'] if ids is None else ids,
                              specialized=specialized, direct_evidence=True,
                              explanation='Paraphrased model reasoning, not source evidence.')])

    def submit(self, results, jobs=None, profile=PROFILE):
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=SourceQualificationBatch(results=results))
        return screen_selected(self.store, jobs or [self.job], profile, paid=True, approved=True)

    def test_catalog_is_deterministic_lossless_with_unique_ids_and_context(self):
        catalog = build_evidence_catalog(PROFILE)
        self.assertEqual(catalog, build_evidence_catalog(PROFILE))
        self.assertEqual([e['evidence_id'] for e in catalog], ['P001', 'P002', 'P003', 'P004'])
        self.assertEqual(catalog[1]['text'], '- Coordinated onboarding and training.\r\n  Managed service delivery for content teams.')
        self.assertEqual(catalog[1]['section'], 'Implementation experience')
        for item in catalog:
            self.assertEqual(item['text'], PROFILE[item['start']:item['end']])
        self.assertFalse(any(e['text'].startswith('#') for e in catalog))

    def test_catalog_distinguishes_identical_paragraphs_and_empty_profiles(self):
        catalog = build_evidence_catalog('Repeated paragraph.\n\nRepeated paragraph.')
        self.assertEqual([e['evidence_id'] for e in catalog], ['P001', 'P002'])
        self.assertNotEqual(catalog[0]['start'], catalog[1]['start'])
        self.assertEqual(build_evidence_catalog('  \n# Headings only\n'), [])

    def test_empty_catalog_is_rejected_before_a_paid_request(self):
        with self.assertRaisesRegex(ValueError, 'no source paragraphs'):
            screen_batch([self.job], '# Headings only\n', approved=True)
        self.runner.assert_not_called()

    def test_multiple_supporting_ids_resolve_to_exact_profile_text(self):
        results, calls = self.submit([self.assessment(['P002', 'P003'])])
        requirement = results[0]['requirements'][0]
        catalog = build_evidence_catalog(PROFILE)
        self.assertEqual(requirement['candidate_quotes'], [catalog[1]['text'], catalog[2]['text']])
        self.assertEqual(requirement['candidate_evidence_ids'], ['P002', 'P003'])
        self.assertEqual(results[0]['classification'], 'Plausible Fit')
        self.assertEqual(results[0]['evidence_format'], 'source-ids-v1')
        self.assertEqual(results[0]['profile_sha256'], profile_digest(PROFILE))
        self.assertEqual(calls, 1)

    def test_missing_evidence_is_unknown_not_absence(self):
        result = validate_result(self.assessment([], 'unknown'), self.job, PROFILE)
        requirement = result.requirements[0]
        self.assertEqual(requirement.candidate_quotes, [])
        self.assertEqual(requirement.evidence_status, 'not evidenced')
        self.assertFalse(requirement.direct_evidence)
        self.assertTrue(requirement.verification_question)
        self.assertEqual(result.classification, 'Needs Verification')

    def test_fabricated_ids_downgrade_only_affected_requirement_and_are_not_echoed(self):
        model = self.assessment(['PRIVATE fabricated reference'])
        model.requirements.append(self.assessment().requirements[0].model_copy(update={
            'job_quote': 'Required Qualifications:', 'importance': 'preferred'}))
        results, _ = self.submit([model])
        invalid, valid = results[0]['requirements']
        self.assertEqual(invalid['status'], 'unknown')
        self.assertEqual(invalid['candidate_quotes'], [])
        self.assertFalse(invalid['direct_evidence'])
        self.assertTrue(invalid['evidence_warnings'])
        self.assertTrue(invalid['verification_question'])
        self.assertEqual(valid['status'], 'supported')
        self.assertNotIn('PRIVATE', json.dumps(results))
        self.assertEqual(len(self.store.screening_history(self.job['id'])), 1)

    def test_mixed_valid_invalid_ids_retain_source_but_never_positive_status(self):
        result = validate_result(self.assessment(['P002', 'P999']), self.job, PROFILE)
        requirement = result.requirements[0]
        self.assertEqual(requirement.status, 'unknown')
        self.assertEqual(requirement.candidate_evidence_ids, ['P002'])
        self.assertEqual(requirement.candidate_quotes, [build_evidence_catalog(PROFILE)[1]['text']])
        self.assertFalse(requirement.direct_evidence)

    def test_positive_or_negative_claim_without_ids_is_downgraded(self):
        for status in ('supported', 'partially supported', 'unsupported'):
            with self.subTest(status=status):
                requirement = validate_result(self.assessment([], status), self.job, PROFILE).requirements[0]
                self.assertEqual(requirement.status, 'unknown')
                self.assertTrue(requirement.evidence_warnings)
                self.assertTrue(requirement.verification_question)

    def test_paraphrases_are_never_source_citations_and_provider_schema_has_no_quotes(self):
        model = self.assessment().model_dump()
        model['requirements'][0]['candidate_quotes'] = ['Invented world-class fintech achievement.']
        output = SourceQualificationBatch.model_validate({'results': [model]})
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=output)
        result = screen_batch([self.job], PROFILE, approved=True)[0]
        self.assertEqual(result.requirements[0].candidate_quotes, [build_evidence_catalog(PROFILE)[1]['text']])
        self.assertNotIn('Invented world-class', result.model_dump_json())
        agent, request_text = self.runner.call_args.args
        schema = AgentOutputSchema(agent.output_type)
        fields = schema.json_schema()['$defs']['SourceRequirement']['properties']
        self.assertIn('candidate_evidence_ids', fields)
        self.assertNotIn('candidate_quotes', fields)
        self.assertNotIn('verification_question', fields)
        parsed = schema.validate_json(output.model_dump_json())
        self.assertEqual(parsed.results[0].requirements[0].candidate_evidence_ids, ['P002'])
        request = json.loads(request_text)
        self.assertEqual(request['candidate_evidence_catalog'], build_evidence_catalog(PROFILE))
        self.assertEqual(request['candidate_profile_sha256'], profile_digest(PROFILE))
        self.assertNotIn('candidate_profile', request)

    def test_transferable_implementation_does_not_establish_specialized_experience(self):
        for quote in ('Corporate card implementation experience required.',
                      'Fintech integration experience required.',
                      'Financial-system integration experience required.'):
            with self.subTest(quote=quote):
                job = fixture(quote)
                result = validate_result(self.assessment(job=job, specialized=False), job, PROFILE)
                self.assertEqual(result.requirements[0].status, 'partially supported')
                self.assertFalse(result.requirements[0].direct_evidence)
                self.assertEqual(result.classification, 'Needs Verification')

    def test_direct_specialized_experience_requires_positive_source_not_negative_mention(self):
        job = fixture('Corporate card implementation experience required.')
        positive = 'Implemented corporate card integrations for enterprise customers.'
        result = validate_result(self.assessment(['P001'], job=job), job, positive)
        self.assertEqual(result.classification, 'Plausible Fit')
        for negative in ('No corporate card implementation experience.', 'Corporate card experience: none.'):
            result = validate_result(self.assessment(['P001'], job=job), job, negative)
            self.assertEqual(result.classification, 'Needs Verification')
            self.assertFalse(result.requirements[0].direct_evidence)

    def test_motive_engine_remain_specialized_mismatches_with_only_transferable_sources(self):
        for description in (MOTIVE, ENGINE):
            job = fixture(description)
            requirements = [SourceRequirement(
                job_quote=line, importance='mandatory', status='supported', candidate_evidence_ids=['P002'],
                specialized=True, direct_evidence=True, explanation='Generic implementation claimed as industry experience.')
                for line in description.splitlines()[1:]]
            result = validate_result(SourceQualificationResult(job_id=job['id'], requirements=requirements,
                                                             explanation='Fictional assessment.'), job, PROFILE)
            self.assertEqual(result.classification, 'Likely Mismatch')
            self.assertIn('not proof of absent credentials', result.explanation)
            self.assertTrue(any(r.verification_question for r in result.requirements))

    def test_partial_batch_preserves_independent_success_on_invalid_job_requirement(self):
        other = fixture(title='Fictional Invalid Job', suffix='partial')
        self.store.upsert_candidates([('Example', other, 'Remote', 'Verify')])
        bad = self.assessment(job=other)
        bad.requirements[0].job_quote = 'Invented job requirement.'
        with self.assertRaises(BatchScreeningError) as raised:
            self.submit([self.assessment(), bad], jobs=[self.job, other])
        self.assertEqual(raised.exception.saved_count, 1)
        self.assertEqual(self.store.screening(self.job['id'])['mode'], 'ai')
        self.assertIsNone(self.store.screening(other['id']))
        self.assertEqual(self.runner.call_count, 1)

    def test_old_history_remains_unchanged_and_cache_versions_cannot_mix(self):
        old = dry_screen(self.job, PROFILE).model_dump()
        old.pop('evidence_format')
        old.pop('profile_sha256')
        for requirement in old['requirements']:
            requirement.pop('candidate_evidence_ids')
            requirement.pop('evidence_warnings')
        self.store.save_screening(self.job['id'], 'old-quotation-key', 'ai', old)
        self.assertIsNone(self.store.screening(self.job['id'], cache_key(self.job, PROFILE)))
        self.submit([self.assessment()])
        history = self.store.screening_history(self.job['id'])
        self.assertEqual(len(history), 2)
        self.assertTrue(any(row['result'] == old for row in history))
        self.assertNotEqual(cache_key(self.job, PROFILE), cache_key(self.job, PROFILE + '\nA new paragraph.'))

    def test_every_request_requires_approval_including_after_invalid_ids(self):
        with self.assertRaises(PermissionError):
            screen_batch([self.job], PROFILE)
        with self.assertRaises(PermissionError):
            screen_selected(self.store, [self.job], PROFILE, paid=True)
        self.runner.assert_not_called()
        self.submit([self.assessment(['P999'])])
        with self.assertRaises(PermissionError):
            screen_selected(self.store, [self.job], PROFILE, paid=True, force=True)
        self.assertEqual(self.runner.call_count, 1)

    def test_legacy_quotation_model_output_cannot_enter_new_paid_screening_flow(self):
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=QualificationBatch(results=[dry_screen(self.job, PROFILE)]))
        with self.assertRaises(BatchScreeningError):
            screen_batch([self.job], PROFILE, approved=True)
        self.assertIsNone(self.store.screening(self.job['id']))


if __name__ == '__main__':
    unittest.main()
