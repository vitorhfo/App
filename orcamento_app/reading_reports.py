"""Persist the evidence of the last import in the same material transaction."""
import json


def ensure_reading_reports(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS reading_reports (
        project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        report_json TEXT NOT NULL,
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')


def save_reading_report(conn, project_id, report):
    ensure_reading_reports(conn)
    conn.execute('''INSERT INTO reading_reports(project_id, report_json)
        VALUES (?, ?) ON CONFLICT(project_id) DO UPDATE SET
        report_json=excluded.report_json, imported_at=CURRENT_TIMESTAMP''',
        (project_id, json.dumps(report, ensure_ascii=False)))


def get_reading_report(conn, project_id):
    # Existing databases can still be inspected before the next app startup.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reading_reports'").fetchone():
        return None
    row = conn.execute('SELECT report_json, imported_at FROM reading_reports WHERE project_id=?',
                       (project_id,)).fetchone()
    if row is None:
        return None
    return {**json.loads(row[0]), 'imported_at': row[1]}
