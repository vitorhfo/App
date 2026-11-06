"""A recalculated numeric cache must not look like an edited template cell."""
import unittest

import xlrd
from xlrd.sheet import Cell

from verify_real_export import same_template_cell


class TemplateVerificationTests(unittest.TestCase):
    def test_accepts_only_numeric_recalculation_noise_seen_in_aluminium_template(self):
        self.assertTrue(same_template_cell(Cell(xlrd.XL_CELL_NUMBER, 5.385684816),
                                           Cell(xlrd.XL_CELL_NUMBER, 5.3856848159999995)))

    def test_rejects_real_numeric_edits_and_missing_or_changed_text_cells(self):
        for before, after in [(Cell(xlrd.XL_CELL_NUMBER, 500), Cell(xlrd.XL_CELL_NUMBER, 501)),
                              (Cell(xlrd.XL_CELL_NUMBER, 0), Cell(xlrd.XL_CELL_EMPTY, '')),
                              (Cell(xlrd.XL_CELL_TEXT, 'TUBO'), Cell(xlrd.XL_CELL_TEXT, 'CHAPA'))]:
            with self.subTest(before=before, after=after):
                self.assertFalse(same_template_cell(before, after))


if __name__ == '__main__':
    unittest.main()
