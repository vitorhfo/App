"""Read-only audit of saved materials against their linked part drawings.

This is deliberately conservative: it reports discrepancies but never treats a
generic drawing dimension, a parent title block, or an OCR guess as a repair.
"""

import csv
from datetime import datetime
import json
from pathlib import Path

from database import get_connection
from manual_validation import linked_drawing


ROOT = Path(__file__).resolve().parent
FIELDS = ('length', 'width', 'depth', 'thickness', 'radius_diam')


def changed(old, new):
    return abs(float(old or 0) - float(new or 0)) > max(0.05, abs(float(new or 0)) * 0.005)


def audit(output_dir=None):
    output_dir = Path(output_dir or ROOT / 'data' / 'audits')
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = output_dir / f'saved_readings_{stamp}.csv'
    json_path = output_dir / f'saved_readings_{stamp}.json'
    conn = get_connection()
    try:
        projects = [dict(row) for row in conn.execute('SELECT * FROM projects ORDER BY id')
                    if row['folder_path'] and not row['name'].startswith(('Teste de upload', 'Estrutura de teste'))]
        manually_edited = {row[0] for row in conn.execute('SELECT DISTINCT material_id FROM material_changes')}
        findings = []
        summary = []
        for project in projects:
            root = Path(project['folder_path'])
            items = [dict(row) for row in conn.execute('SELECT * FROM materials WHERE project_id=?',
                                                        (project['id'],))]
            stats = dict(project_id=project['id'], name=project['name'], items=len(items),
                         source_folder_exists=root.is_dir(), source_pdf_links=0,
                         missing_source_pdfs=0, linked_part_drawings=0,
                         dimension_discrepancies=0, weight_below_drawing=0,
                         manual_items=sum(item['id'] in manually_edited for item in items))
            for item in items:
                source = item.get('source_page') or ''
                if '#page=' not in source:
                    continue
                stats['source_pdf_links'] += 1
                relative = source.rsplit('#page=', 1)[0]
                pdf = (root / relative).resolve()
                if not root.is_dir() or not pdf.is_relative_to(root.resolve()) or not pdf.is_file():
                    stats['missing_source_pdfs'] += 1
                    findings.append(dict(project_id=project['id'], item_id=item['id'],
                                         description=item['description'], issue='source_pdf_missing',
                                         field='', saved='', drawing='', manually_edited=item['id'] in manually_edited,
                                         source_page=source))
                    continue
                drawing = linked_drawing(conn, item)
                if not drawing:
                    continue
                stats['linked_part_drawings'] += 1
                for field in FIELDS:
                    expected = drawing.get('diameter' if field == 'radius_diam' else field) or 0
                    if expected <= 0 or not changed(item.get(field), expected):
                        continue
                    stats['dimension_discrepancies'] += 1
                    findings.append(dict(project_id=project['id'], item_id=item['id'],
                                         description=item['description'], issue='dimension_difference',
                                         field=field, saved=item.get(field), drawing=expected,
                                         manually_edited=item['id'] in manually_edited,
                                         source_page=source))
                expected_mass = drawing.get('unit_weight') or 0
                saved_mass = (item.get('finished_unit_weight') if item.get('wire_allowance_mm')
                              else item.get('unit_weight')) or 0
                if expected_mass > 0 and saved_mass < expected_mass * 0.98:
                    stats['weight_below_drawing'] += 1
                    findings.append(dict(project_id=project['id'], item_id=item['id'],
                                         description=item['description'], issue='weight_below_drawing',
                                         field='unit_weight', saved=saved_mass, drawing=expected_mass,
                                         manually_edited=item['id'] in manually_edited,
                                         source_page=source))
            summary.append(stats)
            print(json.dumps(stats, ensure_ascii=False), flush=True)
        with csv_path.open('w', newline='', encoding='utf-8-sig') as stream:
            columns = ('project_id', 'item_id', 'description', 'issue', 'field',
                       'saved', 'drawing', 'manually_edited', 'source_page')
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(findings)
        json_path.write_text(json.dumps({'summary': summary, 'findings': findings},
                                        ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'FINDINGS={len(findings)} CSV={csv_path} JSON={json_path}', flush=True)
        return summary, findings
    finally:
        conn.close()


if __name__ == '__main__':
    audit()
