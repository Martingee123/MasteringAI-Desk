"""Fictional continuation with real worksheet/numeric checks and no live calls."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import agent_team as team
import live_run
import one_desk as desk
from test_one_desk import FictionalPipeline, NOW


class ContinueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.template_dir.cleanup)
        cls.template = Path(cls.template_dir.name)/'partial'
        cls.template.mkdir()
        for source, name in [('spinoff_worksheet.txt', 'spinoff_worksheet.txt'),
                             ('spinoff_factors.txt', 'spinoff_factors.txt'),
                             ('roles/investment_advisor.txt', 'investment_advisor.txt'),
                             ('roles/verifier.txt', 'verifier_persona.txt')]:
            shutil.copyfile(desk.ROOT/source, cls.template/name)
        # Only fixture creation uses a team, with fully scripted HTTP responses.
        with redirect_stdout(io.StringIO()):
            FictionalPipeline().team('TEST', cls.template, Mock())
        desk.write_json(cls.template/'seven_steps_output.json', {'steps': list(range(1, 8))})
        desk.write_json(cls.template/'registry.json', {'candidates': {}})
        desk.write_json(cls.template/'reader_snapshot.json', {'False/False': []})

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root/'partial'
        shutil.copytree(self.template, self.folder)
        live_run.reference(self.folder, 'verified_report', self.folder/'verified_report.md')
        self.pipeline = FictionalPipeline()
        self.pipeline.folder = self.folder
        self.stdout = io.StringIO()
        stack = self.enterContext(ExitStack())
        for obj, name in ((team, 'TeamManager'), (team.NodeClient, 'call'), (team.Verifier, 'run'),
                          (desk.Pipeline, 'team'), (desk.Pipeline, 'seeker'),
                          (desk, 'SavedSEC'), (desk, 'select_screen')):
            stack.enter_context(patch.object(obj, name, side_effect=AssertionError('Forbidden workflow: '+name)))
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('Network/model forbidden')))
        stack.enter_context(patch('closes_reader.dotenv_values', side_effect=AssertionError('Live export forbidden')))

    def external_verification(self):
        target = self.root/'verify_only'
        target.mkdir()
        for path in self.folder.iterdir():
            if path.is_file() and (path.name.startswith('verifier_') or path.name in
                    {'verified_report.md', 'compiled_report.md', 'verification_marks.json',
                     '10-K.txt', '10-Q.txt', '8-K.txt', 'earnings_release.txt', 'facts.json', 'input_facts.json'}):
                shutil.copyfile(path, target/path.name)
        desk.write_json(target/'verification_origin.json', {'saved_run': str(self.folder.resolve())})
        for path in (self.folder/'live_references').glob('verified_report_*.json'):
            path.unlink()
        live_run.reference(self.folder, 'verified_report', target/'verified_report.md')
        # Match a real failed original: no successful semantic result bundle here.
        for path in self.folder.glob('verifier_semantic*'):
            path.unlink()
        return target

    def run_continue(self):
        with redirect_stdout(self.stdout):
            return desk.continue_run(self.folder, settings={'API_KEY': 'offline'},
                                     pipeline=self.pipeline, now=NOW)

    def test_native_success_fixed_order_exact_composition_and_replay_without_verifier(self):
        self.assert_completed()

    def test_verify_only_provenance_success_and_replay_without_verifier(self):
        self.external_verification()
        self.assert_completed()

    def assert_completed(self):
        protected = {p: p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        final = self.run_continue()
        self.assertEqual(final, self.folder/'desk_report.md')
        self.assertEqual(self.pipeline.events, ['worksheet', 'worksheet hook', 'final hook'])
        self.assertEqual(self.pipeline.judgment_calls, 1)
        manifest = desk.read_json(self.folder/'desk_manifest.json')
        self.assertEqual(manifest['status'], 'completed')
        self.assertEqual(manifest['order'], list(desk.CONTINUE_ORDER))
        self.assertEqual(final.read_bytes(), desk.compose(self.folder, manifest))
        self.assertTrue(final.read_bytes().startswith(b'Filings read: '))
        self.assertIn((self.folder/'verified_report.md').read_bytes(), final.read_bytes())
        self.assertIn(desk.view_section(self.folder/manifest['worksheet']), final.read_bytes())
        for part in desk.CONTINUE_ORDER:
            self.assertIn('[desk] '+part+' elapsed seconds:', self.stdout.getvalue())
        self.assertEqual(self.stdout.getvalue().splitlines()[-1].split(' elapsed seconds:')[0], '[desk] Final report')
        for path, data in protected.items():
            self.assertEqual(path.read_bytes(), data)
        before = {p: p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        with redirect_stdout(io.StringIO()):
            self.assertEqual(desk.replay(self.folder), final)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with self.assertRaisesRegex(desk.PartFailure, 'cannot overwrite'):
            self.run_continue()
        self.assertEqual(self.pipeline.judgment_calls, 1)

    def test_missing_provenance_stops_before_worksheet(self):
        self.external_verification()
        for path in (self.folder/'live_references').glob('*.json'):
            path.unlink()
        self.assert_preflight_fails('provenance')

    def test_wrong_verify_only_origin_stops_before_worksheet(self):
        target = self.external_verification()
        desk.write_json(target/'verification_origin.json', {'saved_run': str(self.root/'wrong')})
        self.assert_preflight_fails('origin')

    def test_missing_verify_only_origin_stops_before_worksheet(self):
        (self.external_verification()/'verification_origin.json').unlink()
        self.assert_preflight_fails('verification_origin')

    def test_changed_compiled_report_or_evidence_stops_before_worksheet(self):
        self.external_verification()
        for name in ('compiled_report.md', '10-K.txt', 'facts.json'):
            with self.subTest(name=name):
                path = self.folder/name
                original = path.read_bytes()
                if name.endswith('.json'):
                    value = desk.read_json(path); value['changed'] = True
                    desk.write_json(path, value)
                else:
                    path.write_bytes(original+b'\nchanged evidence\n')
                self.assert_preflight_fails('evidence changed')
                path.write_bytes(original)

    def test_changed_view_or_published_verified_report_stops_before_worksheet(self):
        self.external_verification()
        for name in ('view.json', 'verified_report.md'):
            with self.subTest(name=name):
                path = self.folder/name; original = path.read_bytes()
                path.write_bytes(original+b'\nchanged\n')
                self.assert_preflight_fails('provenance')
                path.write_bytes(original)

    def test_incomplete_or_changed_semantic_evidence_stops_before_worksheet(self):
        target = self.external_verification()
        path = target/'verifier_semantic_results.json'
        value = desk.read_json(path); value['complete'] = False
        desk.write_json(path, value)
        self.assert_preflight_fails('incomplete')

    def test_missing_worksheet_input_stops_before_call(self):
        (self.folder/'spinoff_worksheet.txt').unlink()
        self.assert_preflight_fails('spinoff_worksheet')

    def test_saved_sec_adapter_uses_only_hash_checked_cache_and_never_a_transport(self):
        import hashlib
        from desk_continuation import SavedFilesSEC
        url = 'https://example.invalid/saved-document.pdf'
        content = b'%PDF-fictional-saved-source'
        archive = self.folder/'sec_sources'; archive.mkdir(exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()
        (archive/(key+'.bin')).write_bytes(content)
        desk.write_json(archive/(key+'.json'), {'url': url, 'sha256': hashlib.sha256(content).hexdigest()})
        client = SavedFilesSEC(self.folder)
        self.assertEqual(client.get(url).content, content)
        self.assertEqual(client.text(url), content.decode())
        with self.assertRaisesRegex(ValueError, 'Missing'):
            client.text('https://example.invalid/not-saved')
        (archive/(key+'.bin')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'URL/hash'):
            client.get(url)

    def assert_preflight_fails(self, message):
        with self.assertRaisesRegex(desk.PartFailure, message):
            self.run_continue()
        self.assertEqual(self.pipeline.events, [])
        self.assertEqual(self.pipeline.judgment_calls, 0)
        self.assertFalse((self.folder/'desk_continuation_started.json').exists())

    def test_worksheet_failure_stops_checks_assembly_and_second_attempt(self):
        self.pipeline.fail = 'worksheet'
        with self.assertRaisesRegex(desk.PartFailure, 'exact fictional failure'):
            self.run_continue()
        self.assertEqual(self.pipeline.events, ['worksheet'])
        self.assertFalse((self.folder/'desk_manifest.json').exists())
        with self.assertRaisesRegex(desk.PartFailure, 'cannot overwrite'):
            self.run_continue()

    def test_numeric_hook_failure_stops_final_assembly(self):
        self.pipeline.fail = 'worksheet hook'
        with self.assertRaisesRegex(desk.PartFailure, 'exact fictional failure'):
            self.run_continue()
        self.assertEqual(self.pipeline.events, ['worksheet', 'worksheet hook'])
        self.assertEqual(self.pipeline.judgment_calls, 1)
        self.assertFalse((self.folder/'desk_manifest.json').exists())
        self.assertFalse((self.folder/'desk_report.md').exists())

    def test_changed_external_verification_fails_replay(self):
        target = self.external_verification()
        final = self.run_continue()
        path = target/'verification_marks.json'
        value = desk.read_json(path); value[0]['reason'] += ' changed'
        desk.write_json(path, value)
        with redirect_stdout(io.StringIO()), self.assertRaises(desk.PartFailure):
            desk.replay(final.parent)

    def test_cli_continuation_route_and_mixed_modes_rejected(self):
        with patch.object(desk, 'continue_run') as resume, patch.object(desk, 'run') as live, redirect_stdout(io.StringIO()):
            self.assertEqual(desk.main(['--continue', str(self.folder)]), 0)
            resume.assert_called_once_with(self.folder)
            live.assert_not_called()
        for args in (['TEST'], ['screen'], ['--replay', 'other'], ['--start', '2030-01-01'],
                     ['--saved-screen', 'screen', '--reuse-desk', 'other'], ['--output-root', 'other']):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                desk.main(['--continue', str(self.folder)]+args)


if __name__ == '__main__':
    unittest.main()
