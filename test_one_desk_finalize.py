"""Fictional saved worksheets finalized without any workflow or model client."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import one_desk as desk
import live_run
from test_one_desk import FictionalPipeline, NOW


class FinalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.template = Path(cls.temp.name)/'saved'
        cls.template.mkdir()
        for source, name in [('spinoff_worksheet.txt', 'spinoff_worksheet.txt'),
                             ('spinoff_factors.txt', 'spinoff_factors.txt'),
                             ('roles/investment_advisor.txt', 'investment_advisor.txt'),
                             ('roles/verifier.txt', 'verifier_persona.txt')]:
            shutil.copyfile(desk.ROOT/source, cls.template/name)
        # Fixture construction is scripted; finalization below forbids clients.
        with redirect_stdout(io.StringIO()):
            pipeline = FictionalPipeline()
            pipeline.team('TEST', cls.template, Mock())
            desk.write_json(cls.template/'registry.json', {'candidates': {}})
            desk.write_json(cls.template/'reader_snapshot.json', {'False/False': []})
            pipeline.worksheet(cls.template, Mock(), NOW)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)/'partial'
        shutil.copytree(self.template, self.folder)
        for path in (self.folder/'live_references').glob('*.json'):
            path.unlink()
        live_run.reference(self.folder, 'verified_report', self.folder/'verified_report.md')
        self.worksheet = next(self.folder.glob('spinoff_worksheet_*.md'))
        live_run.reference(self.folder, 'worksheet', self.worksheet)
        self.stdout = io.StringIO()
        self.guards = []
        stack = self.enterContext(ExitStack())
        for name in ('one_desk.Pipeline', 'one_desk.SavedSEC', 'one_desk.select_screen',
                     'agent_team.NodeClient', 'agent_team.TeamManager',
                     'desk_verifier.Verifier', 'spinoff_worksheet.JudgmentClient',
                     'spinoff_worksheet.run_worksheet', 'spinoff_seeker.SEC',
                     'requests.sessions.Session.request', 'closes_reader.dotenv_values'):
            self.guards.append(stack.enter_context(patch(name, side_effect=AssertionError('Forbidden: '+name))))

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def finalize(self):
        with redirect_stdout(self.stdout):
            return desk.finalize_run(self.folder)

    def reject(self, pattern):
        with self.assertRaisesRegex(desk.PartFailure, pattern):
            self.finalize()
        self.assertFalse((self.folder/'desk_report.md').exists())
        self.assertFalse((self.folder/'desk_manifest.json').exists())

    def test_success_reuses_exact_worksheet_creates_normal_report_and_replays(self):
        before = {p: p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        final = self.finalize()
        manifest = desk.read_json(self.folder/'desk_manifest.json')
        self.assertEqual(manifest['status'], 'completed')
        self.assertEqual(manifest['order'], list(desk.FINALIZE_ORDER))
        self.assertEqual(manifest['worksheet'], self.worksheet.name)
        self.assertEqual(final.read_bytes(), desk.compose(self.folder, manifest))
        self.assertTrue(final.read_bytes().startswith(b'Filings read: '))
        self.assertIn((self.folder/'verified_report.md').read_bytes(), final.read_bytes())
        self.assertIn(desk.view_section(self.worksheet), final.read_bytes())
        for p, content in before.items():
            self.assertEqual(p.read_bytes(), content)
        for stage in desk.FINALIZE_ORDER:
            self.assertIn('[desk] '+stage+' elapsed seconds:', self.stdout.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(desk.replay(self.folder), final)

    def test_missing_worksheet_provenance_fails(self):
        for p in (self.folder/'live_references').glob('worksheet_*.json'):
            p.unlink()
        self.reject('worksheet provenance')

    def test_changed_worksheet_bytes_fail(self):
        self.worksheet.write_bytes(self.worksheet.read_bytes()+b'\nchanged\n')
        self.reject('worksheet hash/view provenance')

    def test_multiple_worksheet_references_fail_closed(self):
        reference = next((self.folder/'live_references').glob('worksheet_*.json'))
        shutil.copyfile(reference, reference.with_name('worksheet_duplicate.json'))
        self.reject('ambiguous saved worksheet')

    def test_changed_verified_report_or_view_fails(self):
        for name in ('verified_report.md', 'view.json'):
            with self.subTest(name=name):
                path = self.folder/name
                before = path.read_bytes()
                path.write_bytes(before+b'\nchanged\n')
                self.reject('provenance')
                path.write_bytes(before)

    def test_missing_or_inconsistent_semantic_results_fail(self):
        path = self.folder/'verifier_semantic_results.json'
        before = path.read_bytes()
        path.unlink()
        self.reject('verification artifact')
        path.write_bytes(before)
        value = desk.read_json(path)
        value['complete'] = False
        desk.write_json(path, value)
        self.reject('incomplete or inconsistent')

    def test_changed_compiled_report_fails(self):
        path = self.folder/'compiled_report.md'
        path.write_bytes(path.read_bytes()+b'\nchanged\n')
        self.reject('evidence changed')

    def test_existing_provenance_linked_numeric_failure_stops_before_assembly(self):
        self.worksheet.write_bytes(self.worksheet.read_bytes()+b'\nInvented amount: 987654321 USD\n')
        for p in (self.folder/'live_references').glob('worksheet_*.json'):
            p.unlink()
        live_run.reference(self.folder, 'worksheet', self.worksheet)
        self.reject('Numeric hook:.*987654321')

    def test_completed_finalization_cannot_be_overwritten(self):
        self.finalize()
        with self.assertRaisesRegex(desk.PartFailure, 'cannot overwrite'):
            self.finalize()

    def test_changed_reference_fails_replay(self):
        self.finalize()
        reference = next((self.folder/'live_references').glob('worksheet_*.json'))
        value = desk.read_json(reference)
        value['sha256'] = '0'*64
        desk.write_json(reference, value)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(desk.PartFailure, 'provenance'):
            desk.replay(self.folder)

    def test_cli_finalize_route_and_incompatible_modes(self):
        with patch.object(desk, 'finalize_run') as finalize, patch.object(desk, 'run') as live:
            self.assertEqual(desk.main(['--finalize', str(self.folder)]), 0)
            finalize.assert_called_once_with(self.folder)
            live.assert_not_called()
        for args in (['TEST'], ['screen'], ['--replay', 'other'], ['--continue', 'other'],
                     ['--start', '2030-01-01'], ['--output-root', 'other'],
                     ['--saved-screen', 'screen', '--reuse-desk', 'other']):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                desk.main(['--finalize', str(self.folder)]+args)


if __name__ == '__main__':
    unittest.main()
