"""The quote contains physical parts, multiplied by each assembly occurrence."""

import unittest
from pathlib import Path
from unittest.mock import patch

from assembly_quantities import scaled_descendants


class AssemblyQuantitiesTest(unittest.TestCase):
    def test_nested_assembly_edit_updates_parts_and_export(self):
        import database
        from app import (MaterialCreate, MaterialUpdate, ProjectCreate, create_material,
                         create_project, get_project_full_data, update_material)
        from template_reports import _calc_pages, _split_items
        test_root = Path(__file__).resolve().parent / 'data' / 'test_runs'
        test_root.mkdir(parents=True, exist_ok=True)
        db_file = test_root / 'assembly_quantities.db'
        if db_file.exists():
            db_file.unlink()
        with patch.object(database, 'DB_PATH', str(db_file)):
            database.init_db()
            project = create_project(ProjectCreate(name='Estrutura com repetição'))['id']
            outer = create_material(project, MaterialCreate(
                description='LATERAL', group_name='Subconjunto', item_type='subconjunto',
                parent_assembly='CORPO', quantity=2))['id']
            direct = create_material(project, MaterialCreate(
                description='CHAPA LATERAL', group_name='Chapa', item_type='materia_prima',
                parent_assembly='CORPO / LATERAL', quantity=4,
                length=100, width=50, thickness=1, unit_weight=0.1,
                unit_price=2))['id']
            inner = create_material(project, MaterialCreate(
                description='SUPORTE', group_name='Subconjunto', item_type='subconjunto',
                parent_assembly='CORPO / LATERAL', quantity=6))['id']
            piece = create_material(project, MaterialCreate(
                description='PARAFUSO', group_name='Ferragens', item_type='comprado',
                parent_assembly='CORPO / LATERAL / SUPORTE', quantity=12,
                unit_weight=0.01, unit_price=1))['id']

            result = update_material(project, outer, MaterialUpdate(quantity=3))
            self.assertEqual(result['descendants_updated'], 3)
            materials = {m['id']: m for m in get_project_full_data(project)['materials']}
            self.assertEqual((materials[direct]['quantity'], materials[inner]['quantity'],
                              materials[piece]['quantity']), (6, 9, 18))
            self.assertEqual(materials[piece]['total_price'], 18)

            update_material(project, inner, MaterialUpdate(quantity=12))
            full = get_project_full_data(project)
            materials = {m['id']: m for m in full['materials']}
            self.assertEqual(materials[direct]['quantity'], 6)
            self.assertEqual(materials[piece]['quantity'], 24)
            self.assertEqual(full['markup_result']['cost_mc'], 24)
            groups = _split_items(full['materials'])
            self.assertEqual(len(groups['sheet']), 1)
            self.assertEqual(len(groups['bought']), 1)
            self.assertEqual(_calc_pages(groups)[0]['D29'], 6)
            self.assertEqual(groups['bought'][0]['quantity'], 24)

    def test_mirrored_combined_part_changes_only_one_side_share(self):
        right = {'id': 1, 'item_type': 'subconjunto', 'parent_assembly': 'CORPO',
                 'description': 'LATERAL DIREITA', 'quantity': 1}
        left = {'id': 2, 'item_type': 'subconjunto', 'parent_assembly': 'CORPO',
                'description': 'LATERAL ESQUERDA', 'quantity': 1}
        part = {'id': 3, 'item_type': 'materia_prima',
                'parent_assembly': 'CORPO / LATERAL DIREITA',
                'mirrored_assembly': 'CORPO / LATERAL ESQUERDA',
                'description': 'BARRA', 'quantity': 2, 'unit_weight': 0.5,
                'unit_area': 0.1, 'unit_price': 4}
        changes = scaled_descendants([right, left, part], right, 2)
        self.assertEqual(len(changes), 1)
        updated = changes[0][1]
        self.assertEqual(updated['quantity'], 3)
        self.assertEqual(updated['total_weight'], 1.5)
        self.assertEqual(updated['total_price'], 12)


if __name__ == '__main__':
    unittest.main()
