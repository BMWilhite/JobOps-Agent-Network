"""Fictional regressions for qualification meaning, never live model requests."""
import unittest
from unittest.mock import patch

from candidate_evidence import build_evidence_catalog
from qualification_agent import SourceRequirement, SourceQualificationResult, validate_result, dry_screen
from test_mvp import fixture

ALTERNATIVE = ('6+ years of relevant experience in consulting, banking, private equity, '
               'or Strategy & Operations, combined with in-house at a SaaS company')
HYPERGROWTH = 'Recent experience at a hypergrowth and rapidly scaling SaaS company'
EXPERT = 'Expert with Google Sheets & Excel, with the ability to build data models'


class ScreeningSemanticsTests(unittest.TestCase):
    def setUp(self):
        runner = patch('agents.Runner.run_sync', side_effect=AssertionError('Paid calls forbidden'))
        self.runner = runner.start()
        self.addCleanup(runner.stop)

    def assess(self, quote, profile, ids, status='supported', importance='mandatory', posting=None):
        job = fixture(posting or "What We're Looking For:\n" + quote)
        result = SourceQualificationResult(job_id=job['id'], explanation='Model narrative requiring review.', requirements=[
            SourceRequirement(job_quote=quote, importance=importance, status=status,
                              candidate_evidence_ids=ids, specialized=True, direct_evidence=True,
                              explanation='Elite finance pedigree is mandatory.')])
        return validate_result(result, job, profile)

    def test_evidence_types_distinguish_targets_skills_employment_and_achievements(self):
        profile = ('# Target Roles\n- Business Operations\n- Strategy & Operations\n'
                   '# Skills\n- Spreadsheet analysis\n'
                   '# Employment History\n- Managed customer implementation at Example Services.\n'
                   '# Achievements\n- Reduced onboarding time by 25%.')
        catalog = build_evidence_catalog(profile)
        self.assertEqual([e['evidence_kind'] for e in catalog],
                         ['aspiration', 'aspiration', 'skill', 'employment', 'achievement'])
        self.assertTrue(all(e['text'] == profile[e['start']:e['end']] for e in catalog))

    def test_nested_target_role_headings_remain_aspirations(self):
        profile = '# Target Roles\n## Strategy & Operations\n- SaaS businesses\n'
        self.assertEqual(build_evidence_catalog(profile)[0]['evidence_kind'], 'aspiration')

    def test_preferences_never_establish_role_experience_or_skill(self):
        profile = '# Target Roles\n- Business Operations\n- Strategy & Operations\n- Expert Excel roles\n'
        for quote, ids in [(ALTERNATIVE, ['P001', 'P002']), (EXPERT, ['P003'])]:
            with self.subTest(quote=quote):
                result = self.assess(quote, profile, ids)
                requirement = result.requirements[0]
                self.assertEqual(requirement.status, 'unknown')
                self.assertEqual(requirement.candidate_quotes, [])
                self.assertFalse(requirement.direct_evidence)
                self.assertTrue(requirement.evidence_warnings)
                self.assertTrue(requirement.verification_question)
                self.assertEqual(result.classification, 'Needs Verification')

    def test_strategy_operations_alternative_plus_saas_satisfies_route_without_finance(self):
        profile = ('# Employment History\n'
                   '- Worked six years in Strategy & Operations at a SaaS company.\n'
                   '- No banking experience.')
        result = self.assess(ALTERNATIVE, profile, ['P001'])
        self.assertEqual(result.classification, 'Plausible Fit')
        self.assertEqual(result.requirements[0].status, 'supported')
        self.assertTrue(result.requirements[0].direct_evidence)
        self.assertNotIn('Elite finance pedigree', result.requirements[0].explanation)
        self.assertIn('not an additional mandatory', result.requirements[0].explanation)

    def test_any_listed_finance_path_also_qualifies_with_shared_saas_condition(self):
        for route in ('consulting', 'banking', 'private equity'):
            with self.subTest(route=route):
                profile = f'# Employment History\nWorked six years in {route}, then worked in-house at a SaaS company.'
                self.assertEqual(self.assess(ALTERNATIVE, profile, ['P001']).classification, 'Plausible Fit')

    def test_valid_alternative_does_not_waive_shared_in_house_saas_condition(self):
        profile = '# Employment History\nWorked six years in Strategy & Operations at a retail company.'
        result = self.assess(ALTERNATIVE, profile, ['P001'])
        self.assertEqual(result.classification, 'Needs Verification')
        self.assertFalse(result.requirements[0].direct_evidence)
        self.assertTrue(result.requirements[0].verification_question)

    def test_absent_optional_route_is_not_whole_requirement_contradiction(self):
        profile = '# Employment History\nNo banking experience.'
        result = self.assess(ALTERNATIVE, profile, ['P001'], status='unsupported')
        self.assertEqual(result.requirements[0].status, 'unknown')
        self.assertEqual(result.classification, 'Needs Verification')

    def test_split_finance_fragments_are_grouped_as_one_alternative_requirement(self):
        profile = '# Employment History\nNo banking experience.'
        job = fixture("What We're Looking For:\n" + ALTERNATIVE)
        requirements = [SourceRequirement(job_quote=fragment, importance='mandatory', status='unsupported',
                                         candidate_evidence_ids=['P001'], specialized=True, direct_evidence=False,
                                         explanation='Finance branch declared mandatory.')
                        for fragment in ('banking', 'private equity')]
        result = validate_result(SourceQualificationResult(job_id=job['id'], requirements=requirements,
                                                          explanation='Finance required.'), job, profile)
        self.assertEqual(len(result.requirements), 1)
        self.assertEqual(result.requirements[0].job_quote, ALTERNATIVE)
        self.assertEqual(result.classification, 'Needs Verification')

    def test_hypergrowth_cannot_be_inferred_from_saas_or_saas_like_work(self):
        profiles = ['# Employment History\nWorked at a SaaS company implementing projects.',
                    '# Employment History\nManaged a SaaS-like content service.',
                    '# Skills\n- Hypergrowth SaaS knowledge']
        for profile in profiles:
            for status in ('supported', 'partially supported'):
                with self.subTest(profile=profile, status=status):
                    result = self.assess(HYPERGROWTH, profile, ['P001'], status=status)
                    self.assertEqual(result.requirements[0].status, 'unknown')
                    self.assertFalse(result.requirements[0].direct_evidence)
                    self.assertTrue(result.requirements[0].verification_question)

    def test_documented_hypergrowth_saas_employment_is_direct_evidence(self):
        profile = '# Employment History\nWorked at a hypergrowth, rapidly scaling SaaS company.'
        result = self.assess(HYPERGROWTH, profile, ['P001'])
        self.assertEqual(result.classification, 'Plausible Fit')
        self.assertTrue(result.requirements[0].direct_evidence)

    def test_unknown_is_not_unsupported_without_explicit_contradiction(self):
        quote = 'Corporate card implementation experience required.'
        missing = self.assess(quote, '# Employment History\nManaged generic service onboarding.', ['P001'], status='unsupported')
        negative = self.assess(quote, '# Employment History\nNo corporate card implementation experience.', ['P001'], status='unsupported')
        self.assertEqual(missing.requirements[0].status, 'unknown')
        self.assertEqual(missing.classification, 'Needs Verification')
        self.assertEqual(negative.requirements[0].status, 'unsupported')
        self.assertEqual(negative.classification, 'Likely Mismatch')

    def test_spreadsheet_importance_comes_from_its_own_posting_line(self):
        posting = ("What We're Looking For:\n"
                   'Exceptional spreadsheet / data management skills, SQL proficiency preferred\n' + EXPERT)
        profile = '# Skills\nExpert with Google Sheets & Excel and data modeling.'
        result = self.assess(EXPERT, profile, ['P001'], importance='preferred', posting=posting)
        self.assertEqual(result.requirements[0].importance, 'mandatory')
        self.assertTrue(result.requirements[0].evidence_warnings)
        preview = dry_screen(fixture(posting), profile)
        self.assertEqual(next(r for r in preview.requirements if r.job_quote == EXPERT).importance, 'mandatory')

    def test_moderate_spreadsheets_cannot_establish_expert_excel_and_sheets(self):
        result = self.assess(EXPERT, '# Skills\nModerate spreadsheet and Excel experience.', ['P001'])
        self.assertEqual(result.requirements[0].status, 'partially supported')
        self.assertFalse(result.requirements[0].direct_evidence)
        self.assertTrue(result.requirements[0].verification_question)
        self.assertEqual(result.classification, 'Needs Verification')

    def test_mixed_optional_sql_clause_cannot_reject_or_satisfy_mandatory_spreadsheet_clause(self):
        quote = 'Exceptional spreadsheet / data management skills, SQL proficiency preferred'
        profile = '# Skills\nBeginner SQL.'
        for status in ('supported', 'unsupported'):
            result = self.assess(quote, profile, ['P001'], status=status, importance='preferred')
            self.assertEqual(result.requirements[0].importance, 'unclear')
            self.assertEqual(result.requirements[0].status, 'unknown')
            self.assertEqual(result.classification, 'Needs Verification')

    def test_preferred_qualifications_neither_fill_mandatory_gaps_nor_cause_rejection(self):
        posting = ('Required Qualifications:\n- Team training experience.\n'
                   'Preferred Qualifications:\n- Corporate card industry experience.')
        profile = '# Employment History\nTrained teams.\n\nNo corporate card industry experience.'
        job = fixture(posting)
        mandatory = SourceRequirement(job_quote='Team training experience.', importance='mandatory', status='supported',
                                      candidate_evidence_ids=['P001'], specialized=False, direct_evidence=True, explanation='Training supported.')
        preferred = SourceRequirement(job_quote='Corporate card industry experience.', importance='mandatory', status='unsupported',
                                      candidate_evidence_ids=['P002'], specialized=True, direct_evidence=False, explanation='Explicit negative.')
        result = validate_result(SourceQualificationResult(job_id=job['id'], requirements=[mandatory, preferred], explanation='Profile.'), job, profile)
        self.assertEqual(result.requirements[1].importance, 'preferred')
        self.assertEqual(result.classification, 'Plausible Fit')
        mandatory.status, mandatory.candidate_evidence_ids = 'unknown', []
        preferred.status, preferred.candidate_evidence_ids = 'supported', ['P001']
        result = validate_result(SourceQualificationResult(job_id=job['id'], requirements=[mandatory, preferred], explanation='Profile.'), job, profile)
        self.assertEqual(result.requirements[0].status, 'unknown')
        self.assertEqual(result.classification, 'Needs Verification')


if __name__ == '__main__':
    unittest.main()
