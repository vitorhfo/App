"""Manual field edits stay attached to their physical drawing across reimports."""
import json
from pathlib import Path
import sqlite3
import uuid
import unittest
from unittest.mock import patch

from manual_import_overrides import preserve_manual_values


class ManualImportOverrideTests(unittest.TestCase):
    def test_sequential_manual_edits_survive_project_refresh(self):
        import database
        from app import (ProjectCreate, MaterialCreate, MaterialUpdate,
                         create_project, create_material, update_material,
                         get_project_full_data)

        db_path = (Path(__file__).resolve().parent / 'data' / 'test_runs' /
                   f'manual_edits_{uuid.uuid4().hex}.db')
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with patch.object(database, 'DB_PATH', str(db_path)):
                database.init_db()
                project_id = create_project(ProjectCreate(name='Teste de edições'))['id']
                item_id = create_material(project_id, MaterialCreate(
                    description='CHAPA LATERAL', group_name='Chapa',
                    item_type='materia_prima', quantity=1, unit='un'))['id']
                conn = database.get_connection()
                initial_changes = conn.execute(
                    'SELECT COUNT(*) FROM material_changes WHERE project_id=? AND material_id=?',
                    (project_id, item_id)).fetchone()[0]
                conn.close()

                update_material(project_id, item_id, MaterialUpdate(
                    width=150, length=222.8, thickness=.9,
                    observation='Cotas conferidas manualmente.'))
                update_material(project_id, item_id, MaterialUpdate(
                    quantity=2, observation='Cotas conferidas; 2 peças.'))

                refreshed = get_project_full_data(project_id)
                item = next(row for row in refreshed['materials'] if row['id'] == item_id)
                self.assertEqual((item['width'], item['length'], item['thickness']),
                                 (150, 222.8, .9))
                self.assertEqual(item['quantity'], 2)
                self.assertEqual(item['observation'], 'Cotas conferidas; 2 peças.')
                conn = database.get_connection()
                changes = conn.execute(
                    'SELECT COUNT(*) FROM material_changes WHERE project_id=? AND material_id=?',
                    (project_id, item_id)).fetchone()[0]
                conn.close()
                self.assertEqual(changes, initial_changes + 2)
        finally:
            for suffix in ('', '-wal', '-shm'):
                Path(str(db_path) + suffix).unlink(missing_ok=True)

    def test_matches_same_child_under_reimported_parent_and_keeps_manual_dimensions(self):
        baseline = {
            'id': 12, 'source_page': 'PROJETO/PSAI/PECA.PDF#page=1',
            'drawing_id': 'PECA', 'description': 'PECA', 'raw_code': '',
            'parent_assembly': 'MODULO 02 / LOGO', 'width': 0,
            'length': 0, 'unit_weight': .5,
        }
        after = {**baseline, 'width': 120, 'length': 150,
                 'observation': 'Cotas verificadas no desenho.'}
        parsed = [
            {'source_page': baseline['source_page'], 'drawing_id': 'PECA',
             'description': 'PECA', 'raw_code': '',
             'parent_assembly': 'PRODUTO / MODULO 01 / LOGO',
             'width': 0, 'length': 0, 'unit_weight': .5},
            {'source_page': baseline['source_page'], 'drawing_id': 'PECA',
             'description': 'PECA', 'raw_code': '',
             'parent_assembly': 'PRODUTO / MODULO 02 / LOGO',
             'width': 0, 'length': 0, 'unit_weight': .5},
        ]
        history = [{'material_id': 12, 'before_json': json.dumps(baseline),
                    'after_json': json.dumps(after)}]

        mapped, missed = preserve_manual_values(parsed, history)

        self.assertEqual(mapped, {12: 1})
        self.assertEqual(missed, [])
        self.assertEqual((parsed[0]['width'], parsed[0]['length']), (0, 0))
        self.assertEqual((parsed[1]['width'], parsed[1]['length']), (120, 150))
        self.assertEqual(parsed[1]['observation'], 'Cotas verificadas no desenho.')

    def test_keeps_explicit_weight_edit_but_does_not_copy_derived_totals(self):
        baseline = {
            'id': 9, 'source_page': 'P.pdf#page=1', 'drawing_id': 'ARAME',
            'description': 'ARAME', 'raw_code': '', 'parent_assembly': 'PAI',
            'group_name': 'Arame', 'radius_diam': 4, 'length': 200,
            'quantity': 2, 'unit_weight': .02, 'total_weight': .04,
        }
        after = {**baseline, 'unit_weight': .025, 'total_weight': .05}
        parsed = [{**baseline, 'unit_weight': .02, 'total_weight': .04}]

        mapped, missed = preserve_manual_values(parsed, [{
            'material_id': 9, 'before_json': json.dumps(baseline),
            'after_json': json.dumps(after),
        }])

        self.assertEqual(mapped, {9: 0})
        self.assertEqual(missed, [])
        self.assertEqual(parsed[0]['unit_weight'], .025)
        self.assertEqual(parsed[0]['total_weight'], .04)

    def test_keeps_weight_calculated_with_manual_geometry_when_geometry_matches(self):
        baseline = {
            'id': 3288, 'source_page': 'PA.pdf#page=2',
            'drawing_id': 'PC00005421', 'description': 'CV STOPPER',
            'raw_code': 'PLPSAB000090', 'parent_assembly': 'PAI',
            'group_name': 'Polímero/PSAI', 'material': 'PSAI BRANCO',
            'thickness': .9, 'width': 0, 'depth': 0, 'length': 612.689,
            'unit_weight': 0, 'unit_area': 0,
        }
        after = {**baseline, 'width': 188, 'unit_weight': .108851,
                 'unit_area': .1152,
                 'observation': 'Peso e cotas conferidos no desenho.'}
        parsed = [{**baseline}]

        mapped, missed = preserve_manual_values(parsed, [{
            'material_id': 3288, 'before_json': json.dumps(baseline),
            'after_json': json.dumps(after),
        }])

        self.assertEqual(mapped, {3288: 0})
        self.assertEqual(missed, [])
        self.assertEqual(parsed[0]['width'], 188)
        self.assertEqual(parsed[0]['unit_weight'], .108851)

    def test_does_not_keep_weight_when_manual_geometry_changed_after_weight(self):
        baseline = {
            'id': 44, 'source_page': 'P.pdf#page=1', 'drawing_id': 'PECA',
            'description': 'PECA', 'raw_code': '', 'parent_assembly': 'PAI',
            'group_name': 'Chapa', 'material': 'ACO', 'thickness': .9,
            'width': 0, 'depth': 0, 'length': 100, 'unit_weight': 0,
        }
        weighed = {**baseline, 'width': 100, 'unit_weight': .07}
        latest = {**weighed, 'width': 120}
        parsed = [{**baseline}]

        mapped, missed = preserve_manual_values(parsed, [
            {'material_id': 44, 'before_json': json.dumps(baseline),
             'after_json': json.dumps(weighed)},
            {'material_id': 44, 'before_json': json.dumps(weighed),
             'after_json': json.dumps(latest)},
        ])

        self.assertEqual(mapped, {44: 0})
        self.assertEqual(missed, [])
        self.assertEqual(parsed[0]['width'], 120)
        self.assertEqual(parsed[0]['unit_weight'], 0)

    @unittest.skipUnless((Path(__file__).resolve().parent / 'data' / 'uploads' /
                          'proj_116' / '2f5fde13ea6d4d54bb5f5aa0a53d4362' /
                          'source').is_dir(), 'Amostra salva Neuroshelf indisponível')
    def test_saved_neuroshelf_geometry_and_weight_survive_folder_reimport(self):
        import database
        from app import get_project_full_data, import_project_folder

        source = (Path(__file__).resolve().parent / 'data' / 'uploads' / 'proj_116' /
                  '2f5fde13ea6d4d54bb5f5aa0a53d4362' / 'source')
        db_path = (Path(__file__).resolve().parent / 'data' / 'test_runs' /
                   f'neuroshelf_reimport_{uuid.uuid4().hex}.db')
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            live = sqlite3.connect(database.DB_PATH)
            target = sqlite3.connect(db_path)
            live.backup(target)
            target.close()
            live.close()

            with patch.object(database, 'DB_PATH', str(db_path)):
                result = import_project_folder(116, folder_path=str(source))
                self.assertEqual(result['materials_count'], 126)
                data = get_project_full_data(116)
                item = next(row for row in data['materials']
                            if row['drawing_id'] == 'PC00005421'
                            and row['description'] == 'CV STOPPER')
                self.assertEqual(item['width'], 188)
                self.assertAlmostEqual(item['unit_weight'], .108851, places=6)

                check = sqlite3.connect(db_path)
                try:
                    link = check.execute('''SELECT COUNT(*) FROM material_changes h
                        JOIN materials m ON m.id=h.material_id
                        WHERE h.project_id=116 AND m.project_id=116
                          AND m.drawing_id='PC00005421' AND m.width=188''').fetchone()[0]
                    self.assertEqual(link, 1)
                finally:
                    check.close()
        finally:
            for suffix in ('', '-wal', '-shm'):
                Path(str(db_path) + suffix).unlink(missing_ok=True)

    @unittest.skipUnless((Path(__file__).resolve().parent / 'data' / 'uploads' /
                          'proj_105' / 'baab0ba1421a4b939cb3a85a87e53032' /
                          'source').is_dir(), 'Amostra enviada de ILHA CASH RECKITT indisponível')
    def test_reimport_uses_parent_and_keeps_manual_edits_and_history(self):
        import database
        from app import get_project_full_data, import_project_folder

        source = (Path(__file__).resolve().parent / 'data' / 'uploads' / 'proj_105' /
                  'baab0ba1421a4b939cb3a85a87e53032' / 'source')
        db_path = (Path(__file__).resolve().parent / 'data' / 'test_runs' /
                   f'cash_reckitt_reimport_{uuid.uuid4().hex}.db')
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            live = sqlite3.connect(database.DB_PATH)
            target = sqlite3.connect(db_path)
            live.backup(target)
            target.close()
            live.close()

            with patch.object(database, 'DB_PATH', str(db_path)):
                before = sqlite3.connect(db_path)
                original_history = before.execute(
                    'SELECT COUNT(*) FROM material_changes WHERE project_id=105'
                ).fetchone()[0]
                before.close()
                result = import_project_folder(105, folder_path=str(source))
                self.assertEqual(result['materials_count'], 202)
                info = get_project_full_data(105)
                self.assertAlmostEqual(info['project']['nominal_weight_pdf'],
                                       197.015608, places=6)
                self.assertEqual(len(info['materials']), 202)

                def find(description, parent_part):
                    return next(m for m in info['materials']
                                if m['description'] == description
                                and parent_part in m['parent_assembly'])

                testera = find('PSAI TESTEIRA Ilha Cash RECKITT - Harpic',
                               'MODULO 02 Ilha Cash RECKITT - Harpic')
                self.assertEqual((testera['width'], testera['length']), (165, 1373.2))
                suporte = find('PSAI SUPORTE Ilha Cash RECKITT',
                               'MODULO 02 Ilha Cash RECKITT - Harpic')
                self.assertEqual((suporte['width'], suporte['length']), (120, 153.1))

                check = sqlite3.connect(db_path)
                try:
                    history = check.execute(
                        'SELECT COUNT(*) FROM material_changes WHERE project_id=105'
                    ).fetchone()[0]
                    links = check.execute('''SELECT COUNT(*) FROM material_changes h
                        JOIN materials m ON m.id=h.material_id
                        WHERE h.project_id=105 AND m.project_id=105''').fetchone()[0]
                    self.assertEqual(history, original_history)
                    self.assertEqual(links, original_history)
                finally:
                    check.close()
        finally:
            for suffix in ('', '-wal', '-shm'):
                Path(str(db_path) + suffix).unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
