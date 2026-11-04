"""Reuse finished Gemini pages between saved copies of one source folder.

Run with explicit project IDs while the local server is stopped. A full SQLite
backup is made before touching each saved copy.
"""

import argparse

from ai_apply_dimensions import _backup_database
from ai_review_queue import reuse_completed_sibling_reviews
from database import get_connection


def _materials(project_id):
    conn = get_connection()
    try:
        return {row['id']: dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=?', (project_id,))}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('projects', type=int, nargs='+')
    args = parser.parse_args()
    for project_id in args.projects:
        before = _materials(project_id)
        backup = _backup_database(project_id)
        reused = reuse_completed_sibling_reviews(project_id)
        after = _materials(project_id)
        changed = [item_id for item_id in before.keys() | after.keys()
                   if before.get(item_id) != after.get(item_id)]
        print(f'Projeto #{project_id}: {reused} página(s) reutilizada(s); '
              f'{len(changed)} material(is) alterado(s); backup={backup}')
        if changed:
            print(f'IDs alterados: {sorted(changed)}')


if __name__ == '__main__':
    main()
