"""Regression for uploaded project folders whose directory is named ``source``."""
from pathlib import Path
import unittest

from reader_v3 import process_complete_project


ROOT = (Path(__file__).resolve().parent / 'data' / 'uploads' / 'proj_105' /
        'baab0ba1421a4b939cb3a85a87e53032' / 'source')


@unittest.skipUnless(ROOT.is_dir(), 'Amostra enviada de ILHA CASH RECKITT indisponível')
class UploadedPackageRootRegression(unittest.TestCase):
    def test_selects_top_assembly_instead_of_largest_harpic_module(self):
        data = process_complete_project(ROOT)

        self.assertEqual(len(data['materials']), 202)
        self.assertAlmostEqual(data['nominal_weight_pdf'], 197.015608, places=6)
        self.assertAlmostEqual(data['nominal_area_pdf'], 67.373681634, places=6)

        assembly_roots = {item['parent_assembly'].split(' / ')[0]
                          for item in data['materials']}
        self.assertEqual(assembly_roots, {'Ilha Cash RECKITT - 150056'})
        module_names = {part for item in data['materials']
                        for part in item['parent_assembly'].split(' / ')
                        if part.startswith('MODULO ')}
        self.assertEqual(module_names, {
            'MODULO 01 Ilha Cash RECKITT - Veja',
            'MODULO 02 Ilha Cash RECKITT - Harpic',
            'MODULO 03 Ilha Cash RECKITT - Vanish',
            'MODULO 04 Ilha Cash RECKITT - Finish',
        })

        harpic_hooks = [item for item in data['materials']
                        if item['description'].startswith('ARAME GANCHO Ilha Cash')]
        self.assertEqual(len(harpic_hooks), 1)
        self.assertEqual(harpic_hooks[0]['quantity'], 12)
        self.assertIn('MODULO 02 Ilha Cash RECKITT - Harpic',
                      harpic_hooks[0]['parent_assembly'])


if __name__ == '__main__':
    unittest.main()
