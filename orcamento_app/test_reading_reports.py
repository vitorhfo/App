"""Reading evidence survives refreshes and rolls back with its material import."""
import sqlite3
import unittest

from reading_reports import ensure_reading_reports, get_reading_report, save_reading_report


class ReadingReportTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY)')
        self.conn.execute('INSERT INTO projects VALUES (1)')
        self.conn.commit()

    def test_legacy_project_does_not_invent_a_reading_history(self):
        self.assertIsNone(get_reading_report(self.conn, 1))
        ensure_reading_reports(self.conn)
        self.assertIsNone(get_reading_report(self.conn, 1))

    def test_report_is_replaced_atomically_and_deleted_with_project(self):
        save_reading_report(self.conn, 1, {'events': [{'profile': 'cad'}]})
        self.conn.commit()
        save_reading_report(self.conn, 1, {'events': [{'profile': 'outpromo'}]})
        self.conn.rollback()
        self.assertEqual(get_reading_report(self.conn, 1)['events'], [{'profile': 'cad'}])
        save_reading_report(self.conn, 1, {'events': [{'profile': 'score'}]})
        self.conn.commit()
        self.assertEqual(get_reading_report(self.conn, 1)['events'], [{'profile': 'score'}])
        self.conn.execute('DELETE FROM projects WHERE id=1')
        self.assertIsNone(get_reading_report(self.conn, 1))


if __name__ == '__main__':
    unittest.main()
