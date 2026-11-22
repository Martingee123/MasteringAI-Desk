"""Read-only prerequisites for continuing a saved, verified One Desk run."""
import hashlib
import json
from pathlib import Path
import re


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child(folder, name):
    path = (folder/name).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError('Missing or unsafe saved verification artifact: '+str(name))
    return path


def subset(selected, saved):
    if isinstance(selected, dict):
        return isinstance(saved, dict) and all(k in saved and subset(v, saved[k]) for k, v in selected.items())
    return selected == saved


def excerpt(text, original):
    lines = original.splitlines()
    for line in text.splitlines():
        match = re.fullmatch(r'L([1-9]\d*): (.*)', line)
        if not match or int(match[1]) > len(lines) or lines[int(match[1])-1] != match[2]:
            raise ValueError('Saved semantic request differs from its cited source lines.')


def validate_verification(folder, expected=None):
    """Validate completed saved results, without executing any Verifier or model.

    The existing live reference binds the published report and frozen view.
    Verify-only additionally needs its original-run provenance. All saved inputs,
    request/response coverage and result copies must agree before reuse.
    """
    from desk_verifier import load_verifier_sources, validate_semantic_response
    folder = Path(folder).resolve()
    report = child(folder, 'verified_report.md')
    view = child(folder, 'view.json')
    matches = []
    for path in sorted((folder/'live_references').glob('verified_report_*.json')):
        link = read(path)
        if link.get('kind') != 'verified_report' or link.get('sha256') != sha(report):
            continue
        artifact = Path(link.get('path', '')).resolve()
        if (link.get('view_sha256') != sha(view) or not artifact.is_file()
                or sha(artifact) != sha(report)):
            raise ValueError('Saved verified report/view provenance does not match.')
        matches.append((path, artifact))
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous successful verification provenance.')
    reference, artifact = matches[0]
    verified = artifact.parent
    names = {'verified_report.md', 'verifier_input.json', 'verifier_output.json',
             'verification_marks.json', 'verifier_code_checks.json',
             'verifier_semantic_batches.json', 'verifier_semantic_results.json'}
    if verified != folder or (verified/'verification_origin.json').exists():
        origin = child(verified, 'verification_origin.json')
        if Path(read(origin).get('saved_run', '')).resolve() != folder:
            raise ValueError('Verify-only origin does not match the original desk run.')
        names.add(origin.name)
    snapshot = read(child(verified, 'verifier_input.json'))
    if load_verifier_sources(folder) != snapshot or load_verifier_sources(verified) != snapshot:
        raise ValueError('Compiled report or saved verification evidence changed.')
    names.update(snapshot['saved_filing_texts'])
    names.update(snapshot['saved_facts'])
    names.add('compiled_report.md')
    result = read(child(verified, 'verifier_output.json'))
    marks = read(child(verified, 'verification_marks.json'))
    if result != {'verified_report': artifact.name, 'marks': marks}:
        raise ValueError('Saved verification result does not match its marks/report.')
    plan = read(child(verified, 'verifier_semantic_batches.json'))
    aggregate = read(child(verified, 'verifier_semantic_results.json'))
    codes = read(child(verified, 'verifier_code_checks.json'))
    semantic = {c['id']: c for c in codes if c.get('semantic')}
    aliases = plan['aliases']
    expected_ids = plan['expected_ids']
    if (aggregate.get('complete') is not True or aggregate.get('aliases') != aliases
            or set(aliases) != set(semantic) or set(aliases.values()) != set(expected_ids)
            or len(expected_ids) != len(set(expected_ids))):
        raise ValueError('Saved semantic verification is incomplete or inconsistent.')
    validate_semantic_response({'checks': aggregate['checks']}, expected_ids)
    fields = ('id', 'original', 'mark', 'reason', 'file', 'quote', 'candidate_quote',
              'period', 'definition', 'semantic', 'quoted_input', 'source_binding', 'calculation_context')
    combined, scheduled = {}, []
    report_text = re.sub(r'<!-- desk-record .*? -->', '', snapshot['compiled_report'])
    for index, batch in enumerate(plan['batches'], 1):
        if batch['batch'] != index:
            raise ValueError('Saved semantic batches are out of order.')
        ids = batch['expected_ids']
        stem = f'verifier_semantic_batch_{index:03d}'
        input_name, output_name = stem+'_input.json', stem+'_output.json'
        request, answer = read(child(verified, input_name)), read(child(verified, output_name))
        node_input, node_output = f'verifier_{index}_input.json', f'verifier_{index}_output.json'
        instructions = f'verifier_{index}_instructions.json'
        if (read(child(verified, node_input)) != request or read(child(verified, node_output)) != answer
                or read(child(verified, instructions)) != {'instructions': child(folder, 'verifier_persona.txt').read_text(encoding='utf-8')}
                or request['expected_output']['properties']['checks']['required'] != ids):
            raise ValueError('Saved semantic request/response provenance does not match.')
        task_checks = json.loads(request['task'].split('Code checks: ', 1)[1])
        if task_checks != [{k: semantic[key][k] for k in fields if k in semantic[key]} for key in ids]:
            raise ValueError('Saved semantic request does not match its code checks.')
        context = request['context']
        if set(context) != {'compiled_report', 'saved_filing_texts', 'saved_facts'}:
            raise ValueError('Unexpected saved semantic context.')
        if ids:
            excerpt(context['compiled_report'], report_text)
        elif context['compiled_report'] != report_text.splitlines()[0]:
            raise ValueError('Saved empty-batch report context changed.')
        for name, text in context['saved_filing_texts'].items():
            if name not in snapshot['saved_filing_texts']:
                raise ValueError('Unknown saved semantic source.')
            excerpt(text, snapshot['saved_filing_texts'][name])
        if not subset(context['saved_facts'], snapshot['saved_facts']):
            raise ValueError('Saved semantic facts differ from the verification inputs.')
        answers = validate_semantic_response(answer, ids)
        if combined.keys() & answers.keys():
            raise ValueError('Duplicate saved semantic results.')
        combined.update(answers)
        scheduled.extend(ids)
        names.update((input_name, output_name, node_input, node_output, instructions))
    if scheduled != expected_ids or combined != aggregate['checks'] or not plan['batches']:
        raise ValueError('Saved semantic batch coverage does not match its completed results.')
    proof = {'reference': reference.relative_to(folder).as_posix(),
             'artifacts': {name: sha(child(verified, name)) for name in sorted(names)}}
    if expected is not None and proof != expected:
        raise ValueError('Saved verification provenance changed after continuation.')
    return proof


def validate_saved_worksheet(folder, expected=None):
    """Resolve one hash-bound existing worksheet; never guess the latest file."""
    folder = Path(folder).resolve()
    view_hash = sha(child(folder, 'view.json'))
    matches = []
    for reference in sorted((folder/'live_references').glob('worksheet_*.json')):
        link = read(reference)
        if link.get('kind') != 'worksheet':
            raise ValueError('Invalid saved worksheet provenance kind.')
        path = Path(link.get('path', '')).resolve()
        if (path.parent != folder or not re.fullmatch(r'spinoff_worksheet_.+\.md', path.name)
                or not path.is_file() or sha(path) != link.get('sha256')
                or link.get('view_sha256') != view_hash):
            raise ValueError('Saved worksheet hash/view provenance does not match.')
        matches.append((reference, path, link))
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous saved worksheet provenance.')
    reference, path, link = matches[0]
    proof = {'reference': reference.relative_to(folder).as_posix(), 'worksheet': path.name,
             'sha256': link['sha256'], 'view_sha256': view_hash}
    if expected is not None and proof != expected:
        raise ValueError('Saved worksheet provenance changed after finalization.')
    return path, proof


def validate_worksheet_inputs(folder):
    from spinoff_worksheet import load_saved_run, Rules
    folder = Path(folder).resolve()
    _, company, _, _ = load_saved_run(folder)
    ticker = company['ticker']
    if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]{0,19}', ticker)
            or read(child(folder, 'view.json')).get('ticker') != ticker
            or read(child(folder, 'seven_steps_output.json')).get('steps') != list(range(1, 8))):
        raise ValueError('Saved desk identity or seven-step completion is inconsistent.')
    read(child(folder, 'registry.json'))
    read(child(folder, 'reader_snapshot.json'))
    Rules.read(child(folder, 'spinoff_worksheet.txt'))
    if not child(folder, 'investment_advisor.txt').read_text(encoding='utf-8').strip():
        raise ValueError('Saved worksheet persona is empty.')
    return ticker


class SavedFilesSEC:
    """Only existing URL/hash-keyed responses; no transport or live fallback."""
    def __init__(self, folder):
        self.folder = Path(folder)

    def _content(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = child(self.folder, 'sec_sources/'+key+'.bin')
        metadata = read(child(self.folder, 'sec_sources/'+key+'.json'))
        if metadata.get('url') != url or metadata.get('sha256') != sha(path):
            raise ValueError('Saved SEC response does not match URL/hash.')
        return path.read_bytes()

    def get(self, url):
        import requests
        response = requests.Response()
        response.status_code, response.url, response._content = 200, url, self._content(url)
        response.encoding = 'utf-8'
        return response

    def text(self, url):
        return self._content(url).decode('utf-8-sig', errors='replace')

    def json(self, url):
        return json.loads(self.text(url))
