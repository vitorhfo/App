"""Reconcile completed AI pages with missing linked part dimensions."""

import argparse

from ai_apply_dimensions import apply_review, review_proposals
from ai_pdf_review import load_review, resolve_pdf
from database import get_connection


def completed_review_candidates(project_id=None):
    conn = get_connection()
    try:
        query = '''SELECT j.project_id,j.path,j.page,j.model,p.folder_path
            FROM ai_review_jobs j JOIN projects p ON p.id=j.project_id
            WHERE j.state='done' '''
        params = []
        if project_id is not None:
            query += 'AND j.project_id=? '
            params.append(project_id)
        query += 'ORDER BY j.project_id,j.path,j.page'
        jobs = [dict(row) for row in conn.execute(query, params)]
    finally:
        conn.close()
    for job in jobs:
        try:
            pdf = resolve_pdf(job['folder_path'] or '', job['path'])
            review = load_review(job['project_id'], job['path'], job['page'],
                                 pdf, job['model'])
            if review is None:
                continue
            proposals = review_proposals(job['project_id'], job['path'],
                                         job['page'], review['result'])
            if proposals:
                yield job, review['result'], proposals
        except (OSError, ValueError):
            # The original result remains visible for manual investigation.
            continue


def run(project_id=None, apply=False):
    found = changed = 0
    for job, result, proposals in completed_review_candidates(project_id):
        found += len(proposals)
        for item, _, fields in proposals:
            print(f"#{job['project_id']} item {item['id']}: {fields} "
                  f"[{job['path']} página {job['page']}]")
        if apply:
            changed += apply_review(job['project_id'], job['path'], job['page'],
                                    result, job['model'])
    print(f'{found} propostas; {changed} itens atualizados.')
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-id', type=int)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(args.project_id, args.apply)
