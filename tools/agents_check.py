"""Offline contract tests: python tools/agents_check.py (no Blender or API key)."""
import copy
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Load pure modules without running the Blender add-on registration package.
for name, path in [('bonsai_sketch_mode', ROOT / 'bonsai_sketch_mode'),
                   ('bonsai_sketch_mode.textmodel', ROOT / 'bonsai_sketch_mode/textmodel')]:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
sys.modules['bonsai_sketch_mode.textmodel.mainthread'] = types.ModuleType('mainthread')
agents = importlib.import_module('bonsai_sketch_mode.textmodel.agents')
requirements = importlib.import_module('bonsai_sketch_mode.requirements')


def action(operation='create_project', parameters=None):
    return dict(operation=operation, parameters=parameters or {}, reason='User requested it')


def result(actions=None):
    return dict(plan=dict(summary='Build', questions=[], actions=actions or [action()]),
                reports={'QA': {'approved': True, 'findings': []}}, ready=True, fingerprint='original')


class AgentChecks(unittest.TestCase):
    def test_five_roles_propose_without_dispatch(self):
        calls = []
        def post(payload, key, endpoint):
            calls.append(payload)
            index = len(calls)
            value = ({'findings': ['Evidence'], 'questions': []} if index <= 3 else
                     result()['plan'] if index == 4 else {'approved': True, 'findings': []})
            return {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'name': 'submit_review', 'input': value}]}
        proposal = agents.propose('Build', {'context': {}, 'fingerprint': 'original'}, 'fake', 'test', post=post)
        self.assertEqual(len(calls), 5)
        self.assertTrue(proposal['ready'])
        self.assertTrue(proposal['requires_approval'])
        self.assertTrue(all([t['name'] for t in p['tools']] == ['submit_review'] for p in calls))

    def test_specialist_question_cannot_be_dropped(self):
        count = 0
        def post(*args):
            nonlocal count
            count += 1
            value = ({'findings': [], 'questions': ['Wall thickness?']} if count <= 3 else
                     result()['plan'] if count == 4 else {'approved': True, 'findings': []})
            return {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'name': 'submit_review', 'input': value}]}
        proposal = agents.propose('Build', {'context': {}, 'fingerprint': 'original'}, 'fake', 'test', post=post)
        self.assertFalse(proposal['ready'])
        self.assertEqual(proposal['plan']['questions'], ['Wall thickness?'])

    def test_truncated_or_refused_response_blocks(self):
        for reason in ['max_tokens', 'refusal', 'end_turn']:
            with self.assertRaises(agents.PlanError):
                agents.propose('Build', {'context': {}, 'fingerprint': 'original'}, 'fake', 'test',
                               post=lambda *a: {'stop_reason': reason})

    def test_stale_plan_never_dispatches(self):
        pending = agents.PendingPlan(result())
        with self.assertRaises(agents.PlanError):
            pending.execute('changed', lambda *a: self.fail('dispatched'))
        self.assertTrue(pending.used)

    def test_single_use_and_copy_isolation(self):
        source = result()
        pending = agents.PendingPlan(source)
        source['plan']['actions'][0]['operation'] = 'delete'
        pending.review()['plan']['actions'].clear()
        self.assertTrue(pending.execute('original', lambda *a: {})['ok'])
        with self.assertRaises(agents.PlanError):
            pending.execute('original', lambda *a: self.fail('replayed'))

    def test_qa_and_questions_block(self):
        for field in ['ready', 'qa', 'questions']:
            proposal = result()
            if field == 'ready': proposal['ready'] = False
            if field == 'qa': proposal['reports']['QA']['approved'] = False
            if field == 'questions': proposal['plan']['questions'] = ['Unknown height']
            with self.assertRaises(agents.PlanError):
                agents.PendingPlan(proposal).execute('original', lambda *a: self.fail('dispatched'))

    def test_unknown_code_bad_types_and_nonfinite_rejected(self):
        for command in [action('eval'), action(parameters={'code': 'bad'}),
                        action('push_pull', {'object': 'x', 'distance': float('nan')}),
                        action('add_walls', {'points': [[0, 0], [1, 1]], 'height': True}),
                        action('add_walls', {'points': [[0, 0], [1, 1]], 'height': -1}),
                        action('assign_class', {'object': {'$ref': '1.object'}, 'ifc_class': 'IfcSlab'})]:
            with self.assertRaises(agents.PlanError):
                agents.validate_plan(result([command])['plan'])

    def test_references_resolve_actual_results(self):
        actions = [action('sketch_polyline', {'points': [[0, 0], [1, 1]]}),
                   action('push_pull', {'object': {'$ref': '0.object'}, 'distance': 1})]
        calls = []
        def dispatch(name, params):
            calls.append((name, params))
            return {'object': 'Actual sketch name'}
        self.assertTrue(agents.PendingPlan(result(actions)).execute('original', dispatch)['ok'])
        self.assertEqual(calls[1][1]['object'], 'Actual sketch name')

    def test_partial_failure_stops_and_cannot_replay(self):
        pending = agents.PendingPlan(result([action(), action('create_type', {'ifc_class': 'IfcWallType'}), action()]))
        calls = []
        def dispatch(name, params):
            calls.append(name)
            if len(calls) == 2: raise ValueError('Bonsai refused')
            return {'created': True}
        execution = pending.execute('original', dispatch)
        self.assertFalse(execution['ok'])
        self.assertEqual(execution['failed_action'], 1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(pending.used)


class RequirementsChecks(unittest.TestCase):
    def test_invalid_stage_is_not_a_pass(self):
        with self.assertRaises(ValueError):
            requirements.check_element('IfcWall', 'typo', {})

    def test_unmapped_and_covering_not_silently_passed(self):
        for ifc_class, predefined in [('IfcUnknown', ''), ('IfcCovering', 'FLOORING')]:
            self.assertEqual(requirements.check_element(ifc_class, 'detailed', {}, predefined)['status'], 'unmapped')

    def test_roof_slab_uses_roof_requirements(self):
        self.assertEqual(requirements.check_element('IfcSlab', 'detailed', {}, 'ROOF')['element'], 'Roof')

    def test_evidence_false_zero_and_empty(self):
        names = requirements.parameter_names('IfcDoor', 'detailed')
        self.assertGreaterEqual(len(names), 3)
        properties = {'UserPset': {names[0]: False, names[1]: 0, names[2]: ''}}
        report = requirements.check_element('IfcDoor', 'detailed', properties)
        self.assertNotIn(names[0], report['missing'])
        self.assertNotIn(names[1], report['missing'])
        self.assertIn(names[2], report['missing'])
        self.assertEqual(report['status'], 'review_required')
        self.assertIn('source', report)


if __name__ == '__main__':
    unittest.main(verbosity=2)
