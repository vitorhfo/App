"""Field-level comparisons must catch silent changes even with equal row counts."""
import copy
import unittest
from unittest.mock import patch

from reading_regression import BASELINES, check_case, differences


class ReadingComparisonTests(unittest.TestCase):
    def test_detects_changes_to_quantity_dimension_material_and_origin(self):
        before = {'materials': [{'description': 'TUBO', 'quantity': 2, 'length': 450,
                                 'material': 'ACO', 'source_page': 'p.pdf#page=3'}]}
        for field, value in [('quantity', 1), ('length', 500), ('material', 'PSAI'),
                             ('source_page', 'p.pdf#page=2')]:
            with self.subTest(field=field):
                after = copy.deepcopy(before)
                after['materials'][0][field] = value
                self.assertEqual([d['field'] for d in differences(before, after)],
                                 [f'materials[0].{field}'])

    def test_duplicate_piece_and_removed_field_are_reported(self):
        self.assertTrue(differences([{'quantity': 2}], [{'quantity': 2}, {'quantity': 2}]))
        self.assertTrue(differences({'length': 0}, {}))
        self.assertEqual(differences({'length': 0}, {'length': 0.0}), [])

    def test_changed_pdf_cannot_be_presented_as_a_successful_reading(self):
        with patch('reading_regression.source_fingerprints', return_value={}):
            with patch('reader_v3.process_complete_project') as reader:
                result = check_case(BASELINES / 'alpa.json')
        self.assertEqual(result['status'], 'changed_sample')
        self.assertTrue(result['differences'])
        reader.assert_not_called()

    def test_unavailable_sample_fails_explicitly_instead_of_skipping(self):
        with patch('reading_regression.ROOT', BASELINES / 'unavailable_source_root'):
            result = check_case(BASELINES / 'alpa.json')
        self.assertEqual(result['status'], 'missing_sample')


class RealReadingBaselineTests(unittest.TestCase):
    def test_all_real_samples_keep_every_recorded_item_field(self):
        paths = sorted(BASELINES.glob('*.json'))
        self.assertGreaterEqual(len(paths), 7, 'As amostras de regressão não podem desaparecer.')
        for path in paths:
            with self.subTest(sample=path.stem):
                result = check_case(path)
                self.assertEqual(result['status'], 'unchanged', str(result)[:3000])
                if path.stem == 'score':
                    selected = [e for e in result['reading_report']['events'] if e['stage'] == 'selected']
                    self.assertEqual({e['source_page'].rsplit('#page=', 1)[1] for e in selected},
                                     {'36', '37'}, 'A origem SCORE deve apontar para a lista, não para a capa.')


if __name__ == '__main__':
    unittest.main()
