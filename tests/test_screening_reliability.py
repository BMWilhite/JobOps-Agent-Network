"""Fictional batches only; every model call is mocked and every database temporary."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.agent_output import AgentOutputSchema
from agents.exceptions import ModelBehaviorError, MaxTurnsExceeded
from jobops_service import screen_selected
from jobops_store import JobOpsStore
from qualification_agent import BatchScreeningError, cache_key, dry_screen
from test_mvp import wire_batch, fixture, PROFILE


class ScreeningReliabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = JobOpsStore(Path(temp.name) / 'batch.db')
        self.store.initialize()
        self.jobs = [fixture(title=f'Fictional Opportunity {i}', suffix=str(i)) for i in range(5)]
        self.store.upsert_candidates([('Example', j, 'Remote', 'Verify') for j in self.jobs])
        runner = patch('agents.Runner.run_sync', side_effect=AssertionError('No real API calls allowed'))
        self.runner = runner.start()
        self.addCleanup(runner.stop)
        config = patch('ai_runtime.private_run_config', return_value=None)
        config.start()
        self.addCleanup(config.stop)

    def submit(self, results, jobs=None):
        self.runner.side_effect = None
        self.runner.return_value = SimpleNamespace(final_output=wire_batch(results=results))
        return screen_selected(self.store, jobs or self.jobs, PROFILE, paid=True, approved=True)

    def result(self, index):
        return dry_screen(self.jobs[index], PROFILE)

    def cached_ids(self):
        return {j['id'] for j in self.jobs if self.store.screening(j['id'], cache_key(j, PROFILE), ai_only=True)}

    def test_missing_result_preserves_four_valid_results_and_requires_new_approval(self):
        with self.assertRaises(BatchScreeningError) as raised:
            self.submit([self.result(i) for i in range(4)])
        error = raised.exception
        self.assertEqual(error.failures, {self.jobs[4]['id']: 'Missing result.'})
        self.assertEqual(error.saved_count, 4)
        self.assertEqual(self.cached_ids(), {j['id'] for j in self.jobs[:4]})
        self.assertIn(self.jobs[4]['title'], str(error))
        with self.assertRaises(PermissionError):
            screen_selected(self.store, self.jobs, PROFILE, paid=True)
        self.assertEqual(self.runner.call_count, 1)
        # Fresh approval targets only the missing job; existing successes reuse cache.
        self.submit([self.result(4)])
        request = json.loads(self.runner.call_args.args[1])
        self.assertEqual([j['job_id'] for j in request['jobs']], [self.jobs[4]['id']])
        self.assertEqual(len(self.cached_ids()), 5)

    def test_duplicate_id_rejects_all_copies_and_preserves_independent_result(self):
        with self.assertRaises(BatchScreeningError) as raised:
            self.submit([self.result(0), self.result(0), self.result(2)], self.jobs[:3])
        self.assertIn('Duplicate ID: 2', raised.exception.failures[self.jobs[0]['id']])
        self.assertEqual(raised.exception.failures[self.jobs[1]['id']], 'Missing result.')
        self.assertEqual(self.cached_ids(), {self.jobs[2]['id']})
        self.assertEqual(self.runner.call_count, 1)

    def test_wrong_id_never_assigned_by_position_or_title(self):
        wrong = self.result(1)
        wrong.job_id = 'unrecognized-private-content-must-not-be-displayed'
        with self.assertRaises(BatchScreeningError) as raised:
            self.submit([self.result(0), wrong], self.jobs[:2])
        self.assertEqual(raised.exception.unexpected_count, 1)
        self.assertNotIn(wrong.job_id, str(raised.exception))
        self.assertEqual(self.cached_ids(), {self.jobs[0]['id']})

    def test_out_of_order_results_match_exact_ids(self):
        results, calls = self.submit([self.result(i) for i in reversed(range(5))])
        self.assertEqual([r['job_id'] for r in results], [j['id'] for j in self.jobs])
        self.assertEqual(calls, 1)
        self.assertEqual(len(self.cached_ids()), 5)

    def test_invalid_evidence_is_not_saved_and_existing_history_survives(self):
        previous = self.result(1).model_dump()
        self.store.save_screening(self.jobs[1]['id'], 'historical-key', 'ai', previous)
        invalid = self.result(1)
        invalid.requirements[0].job_quote = 'Invented job requirement'
        with self.assertRaises(BatchScreeningError) as raised:
            self.submit([self.result(0), invalid], self.jobs[:2])
        self.assertIn('unverifiable job evidence', raised.exception.failures[self.jobs[1]['id']])
        self.assertNotIn('PRIVATE', str(raised.exception))
        self.assertEqual(self.cached_ids(), {self.jobs[0]['id']})
        self.assertEqual(len(self.store.screening_history(self.jobs[1]['id'])), 1)

    def test_full_five_postings_and_only_canonical_ids_in_request_and_schema(self):
        for i, job in enumerate(self.jobs):
            job['source_job_id'] = 'provider-id-' + str(i)
            job['descriptionPlain'] += '\nComplete posting ending ' + str(i)
        self.submit([self.result(i) for i in range(5)])
        agent, request_text = self.runner.call_args.args
        request = json.loads(request_text)
        self.assertEqual(len(request['jobs']), 5)
        for original, sent in zip(self.jobs, request['jobs']):
            self.assertEqual(sent['job_id'], original['id'])
            self.assertEqual(sent['descriptionPlain'], original['descriptionPlain'])
            self.assertNotIn('source_job_id', sent)
            self.assertNotIn('id', sent)
        schema = AgentOutputSchema(agent.output_type)
        identifiers = schema.json_schema()['$defs']['SelectedQualificationResult']['properties']['job_id']['enum']
        self.assertEqual(identifiers, [j['id'] for j in self.jobs])
        parsed = schema.validate_json(self.runner.return_value.final_output.model_dump_json())
        self.assertEqual(len(parsed.results), 5)
        # Missing entries remain parseable so our validator can preserve valid entries.
        partial = schema.validate_json(wire_batch(results=[self.result(0)]).model_dump_json())
        self.assertEqual(len(partial.results), 1)
        self.assertEqual(self.runner.call_args.kwargs['max_turns'], 1)

    def test_unparseable_output_is_actionable_redacted_and_not_retried(self):
        self.runner.side_effect = RuntimeError('API secret and private candidate text')
        with self.assertRaises(BatchScreeningError) as raised:
            screen_selected(self.store, self.jobs, PROFILE, paid=True, approved=True)
        self.assertEqual(len(raised.exception.failures), 5)
        self.assertNotIn('API secret', str(raised.exception))
        self.assertFalse(self.cached_ids())
        self.assertEqual(self.runner.call_count, 1)

    def test_unapproved_submission_does_not_call_model(self):
        with self.assertRaises(PermissionError):
            screen_selected(self.store, self.jobs, PROFILE, paid=True)
        self.runner.assert_not_called()
        self.assertFalse(self.cached_ids())

    def test_schema_and_single_turn_failures_have_safe_specific_reasons(self):
        for exception, expected in [(ModelBehaviorError('PRIVATE response text'), 'required schema'),
                                    (MaxTurnsExceeded('PRIVATE response text'), 'no further model turn')]:
            with self.subTest(exception=type(exception).__name__):
                self.runner.reset_mock()
                self.runner.side_effect = exception
                with self.assertRaises(BatchScreeningError) as raised:
                    screen_selected(self.store, self.jobs, PROFILE, paid=True, approved=True)
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn('PRIVATE', str(raised.exception))
                self.assertEqual(self.runner.call_count, 1)
                self.assertFalse(self.cached_ids())

    def test_empty_assessment_cannot_be_cached_as_a_screened_result(self):
        empty = self.result(1)
        empty.requirements = []
        with self.assertRaises(BatchScreeningError) as raised:
            self.submit([self.result(0), empty], self.jobs[:2])
        self.assertEqual(raised.exception.failures[self.jobs[1]['id']], 'No qualification evidence returned.')
        self.assertEqual(self.cached_ids(), {self.jobs[0]['id']})


if __name__ == '__main__':
    unittest.main()
