"""Offline Research scope/budget regressions through the real node transport."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import agent_team as team
import equity_desk as desk
import research_roles as roles
from insight_contract import INSIGHT_OUTPUT_CONTRACT
from model_budget import MODEL_INPUT_CHAR_LIMIT, request_characters
from research_context import research_evidence_ids, TEXT_BRIEF_LIMIT
from test_agent_team import ScriptedClient, saved_fixture


def large_fixture(folder, *, units=True, period=True):
    saved_fixture(folder)
    # Irrelevant paragraphs greatly exceed the budget but no paragraph is cut.
    noise = ('The legal correspondence archive retains routine administrative correspondence.\n' * 5000)
    table = ('(In millions, except per share amounts)\n' if units else '')
    table += ('Year ended | 2025 | 2024\n' if period else '')
    table += ('Revenue | 120 | 100\nDiluted EPS | 2.40 | 2.00\n'
              '*Revenue includes service and subscription consideration.\n')
    annual = ('Item 1. Business\nThe business sells subscriptions.\n' + noise +
              'Competition\nCustomer demand grew 12% in the period.\nItem 1A. Risks\n'
              'Forbidden risk evidence.\nItem 7. Management Discussion\n'
              'Revenue includes subscriptions.\nSUMMARY RESULTS\n' + table +
              'Item 8. Statements\nForbidden statement evidence.\n')
    (folder/'10-K.txt').write_text(annual, encoding='utf-8')


class ResearchContextTests(unittest.TestCase):
    def manager(self, folder):
        return team.TeamManager(folder, ScriptedClient())

    def plan_summary(self, folder, text):
        large_fixture(folder)
        (folder/'earnings_release.txt').write_text(text, encoding='utf-8')
        (folder/'release_lines.json').write_text('{}', encoding='utf-8')
        manager = self.manager(folder)
        with patch.object(team.requests, 'post', side_effect=AssertionError('No model calls')) as post:
            keys = research_evidence_ids(manager.catalog, manager.research, manager.sources, roles.RoleError)
        post.assert_not_called()
        supplied = manager.catalog.select(keys)
        return manager, {key: row for key, row in supplied.items()
                         if row.get('kind') == 'text' and
                         manager.catalog.sources[row['source_id']]['file'] == 'earnings_release.txt'}

    def summary_table(self, *, title='GAAP Quarterly Financial Results', scale=' ($M)',
                      header="| Q3'26 | Q3'25 | Y/Y | Q2'26 | Q/Q"):
        return (title+'\n'+header+'\nRevenue'+scale+' | $120 | $90 | Up 33% | $100 | Up 20%\n'
                'Diluted earnings per share | $2.40 | $1.80 | Up 33% | $2.00 | Up 20%\n')

    def test_summary_scale_and_compact_quarters_keep_exact_gaap_and_nongaap_source(self):
        text = self.summary_table() + self.summary_table(title='Non-GAAP Quarterly Financial Results')
        with tempfile.TemporaryDirectory() as tmp:
            _, supplied = self.plan_summary(Path(tmp), text)
            rows = text.splitlines()
            self.assertEqual({r['line'] for r in supplied.values()}, set(range(1, len(rows)+1)))
            for row in supplied.values():
                self.assertEqual(row['text'], rows[row['line']-1])

    def test_compact_quarter_spellings_and_comparison_columns_are_preserved(self):
        for quarter in range(1, 5):
            for header in (f"Q{quarter}'31 | Q{quarter} '30 | Y/Y | Q2'31 | Q/Q",
                           f'Q{quarter} 2031 | Q{quarter} 2030 | YoY | Q2 2031 | QoQ'):
                with self.subTest(header=header), tempfile.TemporaryDirectory() as tmp:
                    _, supplied = self.plan_summary(Path(tmp), self.summary_table(header=header))
                    self.assertIn(header, [r['text'] for r in supplied.values()])

    def test_summary_missing_explicit_scale_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(roles.RoleError, 'units/scale'):
            self.plan_summary(Path(tmp), self.summary_table(scale=''))

    def test_summary_missing_period_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(roles.RoleError, 'period/column'):
            self.plan_summary(Path(tmp), self.summary_table(header='| | | | |'))

    def test_malformed_compact_quarters_and_numeric_body_are_not_headers(self):
        for header in ("Q5'31 | Q3'30 | Y/Y", "Q3'3 | Q3'30 | YoY",
                       "Q3'2031 | Q3'30 | Q/Q", 'Q3 31 | Q3 2030 | QoQ',
                       "Q5'31 | Q3'30 | Q2'31", "Q3'31 | 120 | 90"):
            with self.subTest(header=header), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(roles.RoleError, 'period/column'):
                    self.plan_summary(Path(tmp), self.summary_table(header=header))

    def test_previous_table_cannot_supply_missing_scale_or_period(self):
        for missing in ('scale', 'header'):
            kwargs = {missing: ''}
            text = self.summary_table() + self.summary_table(title='OTHER RESULTS', **kwargs)
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(roles.RoleError, 'units/scale' if missing == 'scale' else 'period/column'):
                    self.plan_summary(Path(tmp), text)

    def test_prose_footnote_in_layout_table_is_not_a_numeric_eps_row(self):
        text = (self.summary_table() + 'MEASURE DEFINITIONS\n| | |\n'
                '(*) | This release includes diluted earnings per share; the tax rate for 2031 is 13%.\n')
        with tempfile.TemporaryDirectory() as tmp:
            self.plan_summary(Path(tmp), text)

    def test_unaudited_qualifier_preserves_same_table_metadata(self):
        for qualifier in ('(Unaudited)', 'Unaudited'):
            text = ('FICTIONAL QUARTERLY RESULTS\n(In millions, except per share data)\n' +
                    qualifier + '\n| | Three Months Ended\n| | October 31,\n'
                    '| | 2031 | 2030\nTotal revenue | 120 | 100\n'
                    'Net income per share, diluted | 2.40 | 2.00\n')
            with self.subTest(qualifier=qualifier), tempfile.TemporaryDirectory() as tmp:
                _, supplied = self.plan_summary(Path(tmp), text)
                self.assertEqual({r['text'] for r in supplied.values()}, set(text.splitlines()))

    def test_unaudited_qualifier_does_not_supply_or_borrow_context(self):
        header = '| | Three Months Ended\n| | October 31,\n| | 2031 | 2030\n'
        row = 'Total revenue | 120 | 100\n'
        cases = {
            'missing scale': '(Unaudited)\n' + header + row,
            'missing period': '(In millions)\n(Unaudited)\n' + row,
            'conflicting scale': '(In millions)\nUnaudited\n(In billions)\n' + header + row,
            'conflicting abbreviation': '(In billions)\nUnaudited\n' + header + 'Revenue ($M) | 120 | 100\n',
            'prose boundary': '(In millions)\nThe business expanded during the period.\nUnaudited\n' + header + row,
            'table title boundary': '(In millions)\nOTHER RESULTS\nUnaudited\n' + header + row,
            'section boundary': '(In millions)\nItem 8. Statements\nUnaudited\n' + header + row,
            'earlier table': '(In millions)\n' + header + 'Assets | 70 | 60\nUnaudited\n' + header + row,
            'earlier inline scale': header + 'Assets ($M) | 70 | 60\nUnaudited\n' + header + row,
        }
        for name, text in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(roles.RoleError, 'units/scale|period/column'):
                    self.plan_summary(Path(tmp), text)

    def test_compact_fiscal_quarter_segment_header_keeps_exact_source_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            large_fixture(folder)
            path = folder / '10-K.txt'
            path.write_text(path.read_text(encoding='utf-8').replace(
                'Year ended | 2025 | 2024',
                'Example segment | Q3 FY27 | Q3 FY26 | Change | |'), encoding='utf-8')
            manager = self.manager(folder)
            manager.specialist(roles.RESEARCH)
            supplied = manager.supplied[roles.RESEARCH]
            for text in ('Example segment | Q3 FY27 | Q3 FY26 | Change | |',
                         'Revenue | 120 | 100', '(In millions, except per share amounts)'):
                row = next(row for row in supplied.values() if row.get('text') == text)
                filename = manager.catalog.sources[row['source_id']]['file']
                self.assertEqual((folder / filename).read_text(encoding='utf-8').splitlines()[row['line']-1], text)

    def test_large_filing_actual_first_and_revision_requests_fit_and_remain_source_bound(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            folder = Path(tmp)
            large_fixture(folder)
            persona = roles.load_instructions(roles.RESEARCH)
            client = team.NodeClient('offline', folder)
            manager = team.TeamManager(folder, client)
            scripted = ScriptedClient()
            sent = []

            def model(*args, **kwargs):
                body = kwargs['json']
                envelope = json.loads(body['messages'][1]['content'])
                sent.append(copy.deepcopy(envelope))
                self.assertLessEqual(request_characters(body['messages'][0]['content'], envelope['task'],
                                     envelope['context'], envelope['expected_output']), MODEL_INPUT_CHAR_LIMIT)
                self.assertEqual(body['messages'][0]['content'], persona+'\n\n'+INSIGHT_OUTPUT_CONTRACT)
                output = scripted.call(roles.RESEARCH, envelope['task'], envelope['context'], envelope['expected_output'])
                return Mock(ok=True, json=lambda: {'choices':[{'finish_reason':'stop',
                            'message':{'content':json.dumps(output)}}]})

            with patch.object(team.requests, 'post', side_effect=model) as post:
                manager.specialist(roles.RESEARCH)
                manager.specialist(roles.RESEARCH, {roles.PARTS[1]: ['Clarify the supported growth interpretation.']})
                self.assertEqual(post.call_count, 2)
            self.assertEqual(roles.load_instructions(roles.RESEARCH), persona)
            self.assertEqual(set(sent[0]), {'task','context','expected_output'})
            for envelope in sent:
                context = envelope['context']
                texts = {k:v for k,v in context['evidence'].items() if isinstance(v,str)}
                joined = '\n'.join(texts.values())
                self.assertIn('Revenue | 120 | 100', joined)
                self.assertIn('Diluted EPS | 2.40 | 2.00', joined)
                self.assertIn('(In millions, except per share amounts)', joined)
                self.assertIn('Year ended | 2025 | 2024', joined)
                self.assertIn('*Revenue includes service and subscription consideration.', joined)
                self.assertNotIn('routine administrative correspondence', joined)
                self.assertNotIn('Forbidden', joined)
                self.assertNotIn('step4_facts', context)
                self.assertNotIn('step5_metrics', context)
                self.assertNotIn('price', context['evidence'])
                self.assertTrue(any(k.startswith('peer.') for k in context['evidence']))
                self.assertFalse(any(k.startswith('subject.') for k in context['evidence']))
                margin = next(row for k,row in context['evidence'].items()
                              if k.startswith('peer.') and k.endswith('.operating_margin'))
                self.assertEqual(context['sources'][margin['source_id']]['file'], 'peers.json')
                self.assertTrue(all(ref.startswith('peer.') for ref in margin['inputs']))
                choices = envelope['expected_output']['properties']['insight']['properties']['evidence_ids']['items']['enum']
                self.assertTrue(set(choices) <= set(texts))
                for key,text in texts.items():
                    record = manager.supplied[roles.RESEARCH][key]
                    source = manager.catalog.sources[record['source_id']]
                    actual = (folder/source['file']).read_text(encoding='utf-8').splitlines()
                    self.assertEqual(text, actual[record['line']-1])

    def test_selection_is_deterministic_and_peer_closure_cannot_import_subject_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); large_fixture(folder)
            manager = self.manager(folder)
            choose = lambda: research_evidence_ids(manager.catalog, manager.research, manager.sources, roles.RoleError)
            self.assertEqual(choose(), choose())
            peer = next(k for k in manager.catalog.records if k.startswith('peer.') and k.endswith('.operating_margin'))
            manager.catalog.records[peer]['references'].append('subject.revenue.current')
            with self.assertRaisesRegex(roles.RoleError, 'forbidden desk-step'):
                choose()

    def test_missing_required_period_or_units_fails_before_model(self):
        for field in ('period','units'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp); large_fixture(folder, **{field:False})
                manager = self.manager(folder)
                with patch.object(team.requests, 'post') as post, self.assertRaisesRegex(roles.RoleError, field):
                    manager.specialist(roles.RESEARCH)
                post.assert_not_called()

    def test_required_line_is_never_shortened_to_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); large_fixture(folder)
            p = folder/'10-K.txt'
            original = p.read_text(encoding='utf-8')
            giant = 'Revenue | 120 | 100 | ' + 'Required definition ' * TEXT_BRIEF_LIMIT
            p.write_text(original.replace('Revenue | 120 | 100', giant), encoding='utf-8')
            manager = self.manager(folder)
            with self.assertRaisesRegex(roles.RoleError, 'intact; no evidence was truncated'):
                manager.specialist(roles.RESEARCH)
            self.assertIn(giant, p.read_text(encoding='utf-8'))

    def test_referenced_definition_is_complete_and_missing_definition_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); large_fixture(folder)
            p=folder/'10-K.txt'
            original=p.read_text(encoding='utf-8')
            text=original.replace('*Revenue includes service and subscription consideration.',
                                 '*Refer to the Revenue Definition section.')
            text=text.replace('Item 8. Statements', 'Revenue Definition\nRevenue includes service and subscription consideration.\nItem 8. Statements')
            p.write_text(text,encoding='utf-8')
            manager=self.manager(folder); manager.specialist(roles.RESEARCH)
            supplied=manager.supplied[roles.RESEARCH]
            self.assertIn('Revenue includes service and subscription consideration.', [r.get('text') for r in supplied.values()])
            p.write_text(text.replace('Revenue Definition\nRevenue includes service and subscription consideration.\n',''),encoding='utf-8')
            manager=self.manager(folder)
            with self.assertRaisesRegex(roles.RoleError,'missing referenced Revenue Definition'):
                manager.specialist(roles.RESEARCH)


if __name__ == '__main__':
    unittest.main()
