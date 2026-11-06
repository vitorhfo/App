"""Compare real readings with versioned, explicitly labelled behavior baselines.

There is deliberately no command to overwrite expectations from a fresh parse.
A baseline is evidence of previous behavior, not approval of inferred measures.
"""
from pathlib import Path
import argparse
import hashlib
import json

APP = Path(__file__).resolve().parent
ROOT = APP.parents[1]
BASELINES = APP / 'regression_baselines'


def differences(expected, actual, path=''):
    """Report changed fields, including missing/extra rows and duplicate parts."""
    result = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() | actual.keys()):
            field = f'{path}.{key}' if path else key
            if key not in actual or key not in expected:
                result.append({'field': field, 'expected': expected.get(key),
                               'actual': actual.get(key), 'kind': 'missing_or_extra'})
            else:
                result.extend(differences(expected[key], actual[key], field))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            result.append({'field': f'{path}.count', 'expected': len(expected),
                           'actual': len(actual), 'kind': 'row_count'})
        for index, (before, after) in enumerate(zip(expected, actual)):
            result.extend(differences(before, after, f'{path}[{index}]'))
    elif expected != actual:
        result.append({'field': path, 'expected': expected, 'actual': actual,
                       'kind': 'value'})
    return result


def source_fingerprints(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file() and p.suffix.lower() == '.pdf'}


def check_case(path):
    from reader_v3 import process_complete_project
    case = json.loads(Path(path).read_text(encoding='utf8'))
    folder = ROOT / case['folder']
    result = {'id': case['id'], 'baseline_status': case['status'], 'differences': []}
    if not folder.is_dir():
        return {**result, 'status': 'missing_sample', 'folder': case['folder']}
    source_changes = differences(case['sources'], source_fingerprints(folder), 'sources')
    if source_changes:
        return {**result, 'status': 'changed_sample', 'differences': source_changes}
    data = process_complete_project(folder)
    actual = {field: data.get(field) for field in case['expected']}
    changes = differences(case['expected'], actual)
    return {**result, 'status': 'different' if changes else 'unchanged',
            'differences': changes, 'materials': len(data['materials']),
            'reading_report': data.get('reading_report', {})}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Conferir leituras reais sem alterar o banco.')
    parser.add_argument('--case', action='append', help='Nome de uma amostra; pode repetir.')
    parser.add_argument('--output', type=Path, help='Arquivo JSON com diferenças por campo.')
    args = parser.parse_args(argv)
    paths = sorted(BASELINES.glob('*.json'))
    if args.case:
        unknown = set(args.case) - {p.stem for p in paths}
        if unknown:
            parser.error('Amostras desconhecidas: ' + ', '.join(sorted(unknown)))
        paths = [p for p in paths if p.stem in args.case]
    results = []
    for path in paths:
        try:
            result = check_case(path)
        except Exception as exc:
            result = {'id': path.stem, 'status': 'error', 'error': str(exc)}
        results.append(result)
        print(f"{path.stem}: {result['status']} ({len(result.get('differences', []))} diferenças)", flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    return 0 if results and all(r['status'] == 'unchanged' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
