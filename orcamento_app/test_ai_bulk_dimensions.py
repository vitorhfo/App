"""Bulk import uses saved AI evidence only for missing linked dimensions."""

import json
import unittest

import ai_pdf_review
import database
import test_ai_dimension_application as fixture
from fastapi import HTTPException
from reportlab.pdfgen import canvas
from app import (get_ai_pending_dimensions, import_ai_pending_dimensions,
                 select_ai_discovered_item, WireVariantSelection)


class AiBulkDimensionsTest(unittest.TestCase):
    setUp = fixture.AiDimensionApplicationTest.setUp
    read = fixture.AiDimensionApplicationTest.read

    def _done_review(self, model, length, width):
        result = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'item_type': 'comprado',
            'dimension_basis': 'externa', 'length': length, 'width': width,
            'evidence': f'Cotas {length} x {width} mm no desenho'}]})
        ai_pdf_review.save_review(self.project, 'PSAI FR. Display.pdf', 1,
                                  self.source / 'PSAI FR. Display.pdf', result, model)
        conn = database.get_connection()
        conn.execute('''INSERT INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force)
            VALUES (?,?,1,?,'done',1,0,0)''',
            (self.project, 'PSAI FR. Display.pdf', model))
        conn.commit()
        conn.close()

    def test_button_imports_only_pending_dimensions_and_second_click_is_noop(self):
        from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions

        self._done_review(ai_pdf_review.AUTO_MODEL, 299, 234)
        before = preview_pending_ai_dimensions(self.project)
        self.assertEqual((before['eligible_items'], before['eligible_fields']), (1, 2))
        self.assertEqual(before['pending_items'], 1)
        applied = apply_pending_ai_dimensions(self.project)
        self.assertEqual(applied['applied_items'], 1)
        self.assertEqual(applied['pending_items'], 0)
        self.assertEqual((self.read()['length'], self.read()['width']), (299, 234))
        self.assertEqual(self.read()['quantity'], 2)
        self.assertEqual(self.read()['unit_area'], .131708152)
        self.assertEqual(apply_pending_ai_dimensions(self.project)['applied_items'], 0)

    def test_conflicting_models_stay_pending_without_changing_item(self):
        from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions

        self._done_review(ai_pdf_review.AUTO_MODEL, 299, 234)
        self._done_review(ai_pdf_review.FALLBACK_MODEL, 320, 234)
        preview = preview_pending_ai_dimensions(self.project)
        self.assertEqual(preview['eligible_items'], 0)
        self.assertEqual(preview['conflict_items'], 1)
        self.assertEqual(apply_pending_ai_dimensions(self.project)['applied_items'], 0)
        self.assertEqual((self.read()['length'], self.read()['width']), (0, 0))

    def test_prior_manual_field_remains_empty_while_other_pending_field_imports(self):
        from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions

        conn = database.get_connection()
        conn.execute('''INSERT INTO material_changes(project_id,material_id,before_json,after_json)
            VALUES (?,?,?,?)''',
            (self.project, self.item, json.dumps({'length': 80}), json.dumps({'length': 0})))
        conn.commit()
        conn.close()
        self._done_review(ai_pdf_review.AUTO_MODEL, 299, 234)
        self.assertEqual(preview_pending_ai_dimensions(self.project)['eligible_fields'], 1)
        self.assertEqual(apply_pending_ai_dimensions(self.project)['applied_items'], 1)
        self.assertEqual((self.read()['length'], self.read()['width']), (0, 234))

    def test_project_button_api_previews_then_imports_saved_review(self):
        self._done_review(ai_pdf_review.AUTO_MODEL, 299, 234)
        self.assertEqual(get_ai_pending_dimensions(self.project)['eligible_fields'], 2)
        self.assertEqual(import_ai_pending_dimensions(self.project)['applied_items'], 1)
        self.assertEqual(get_ai_pending_dimensions(self.project)['eligible_fields'], 0)
        with self.assertRaises(HTTPException) as missing:
            get_ai_pending_dimensions(999999)
        self.assertEqual(missing.exception.status_code, 404)

    def test_parent_only_pdf_reports_unlinked_ai_part_without_pricing_it(self):
        from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions

        conn = database.get_connection()
        conn.execute("UPDATE materials SET item_type='subconjunto',group_name='Subconjunto' "
                     'WHERE id=?', (self.item,))
        conn.commit()
        conn.close()
        self._done_review(ai_pdf_review.AUTO_MODEL, 299, 234)
        preview = preview_pending_ai_dimensions(self.project)
        self.assertEqual(preview['eligible_items'], 0)
        self.assertEqual(preview['unlinked_ai_items'], 1)
        self.assertEqual(apply_pending_ai_dimensions(self.project)['applied_items'], 0)
        self.assertEqual((self.read()['length'], self.read()['width']), (0, 0))

    def test_detail_page_matches_part_list_page_in_pending_preview(self):
        from ai_bulk_dimensions import preview_pending_ai_dimensions

        pdf_path = self.source / 'PSAI FR. Display.pdf'
        pdf = canvas.Canvas(str(pdf_path))
        pdf.drawString(50, 700, 'Lista de materiais')
        pdf.showPage()
        pdf.drawString(50, 700, 'Detalhe PSAI FR. Display')
        pdf.save()
        result = ai_pdf_review.normalize_response({'items': [{
            'item_number': '1', 'description': 'PSAI FR. Display',
            'item_type': 'comprado', 'dimension_basis': 'externa',
            'length': 299, 'width': 234,
            'evidence': 'Cotas 299 e 234 mm no detalhe'}]})
        ai_pdf_review.save_review(self.project, 'PSAI FR. Display.pdf', 2,
                                  pdf_path, result, ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        conn.execute('''INSERT INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force)
            VALUES (?,?,2,?,'done',1,0,0)''',
            (self.project, 'PSAI FR. Display.pdf', ai_pdf_review.AUTO_MODEL))
        conn.commit()
        conn.close()
        preview = preview_pending_ai_dimensions(self.project)
        self.assertEqual((preview['eligible_items'], preview['eligible_fields']), (1, 2))
        self.assertEqual(preview['unlinked_ai_items'], 0)

    def test_button_stages_ai_only_wire_and_requires_total_quantity_before_cost(self):
        from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions

        pdf_path = self.source / 'ARAME GANCHO.pdf'
        pdf = canvas.Canvas(str(pdf_path))
        pdf.drawString(50, 700, 'ARAME GANCHO COMPRIMENTO 841 Ø6')
        pdf.save()
        result = ai_pdf_review.normalize_response({'items': [{
            'description': 'ARAME GANCHO', 'item_type': 'materia_prima',
            'material': 'ARAME BTC CLARO Ø6', 'length': 841,
            'radius_diam': 6, 'quantity': 1, 'quantity_scope': 'local_table',
            'dimension_basis': 'corte',
            'evidence': 'Tabela de materiais: COMPRIMENTO 841, Ø6, QTD 1'}]})
        for model in (ai_pdf_review.AUTO_MODEL, ai_pdf_review.FALLBACK_MODEL):
            ai_pdf_review.save_review(self.project, 'ARAME GANCHO.pdf', 1,
                                      pdf_path, result, model)
            conn = database.get_connection()
            conn.execute('''INSERT INTO ai_review_jobs
                (project_id,path,page,model,state,attempts,next_attempt_at,force)
                VALUES (?,?,1,?,'done',1,0,0)''',
                (self.project, 'ARAME GANCHO.pdf', model))
            conn.commit()
            conn.close()
        self.assertEqual(preview_pending_ai_dimensions(self.project)['new_ai_items'], 1)
        applied = apply_pending_ai_dimensions(self.project)
        self.assertEqual((applied['new_ai_items'], applied['pending_ai_items']), (1, 1))
        self.assertEqual(applied['unlinked_ai_items'], 0)
        conn = database.get_connection()
        candidate = dict(conn.execute('SELECT * FROM ai_discovered_items WHERE project_id=?',
                                      (self.project,)).fetchone())
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM materials WHERE project_id=?',
                                      (self.project,)).fetchone()[0], 1)
        conn.close()
        self.assertEqual(candidate['ready'], 1)
        added = select_ai_discovered_item(self.project, candidate['id'],
                                          WireVariantSelection(quantity=10))
        self.assertEqual((added['material']['quantity'], added['material']['drawing_length'],
                          added['material']['length']),
                         (10, 841, 861))
        self.assertEqual(apply_pending_ai_dimensions(self.project)['new_ai_items'], 0)
        with self.assertRaises(HTTPException) as duplicate:
            select_ai_discovered_item(self.project, candidate['id'],
                                      WireVariantSelection(quantity=10))
        self.assertEqual(duplicate.exception.status_code, 409)

    def test_existing_wire_with_welding_allowance_is_not_staged_again(self):
        from ai_bulk_dimensions import preview_pending_ai_dimensions

        pdf_path = self.source / 'ARAME GANCHO.pdf'
        pdf = canvas.Canvas(str(pdf_path))
        pdf.drawString(50, 700, 'ARAME GANCHO COMPRIMENTO 841 Ø6')
        pdf.save()
        conn = database.get_connection()
        conn.execute('''INSERT INTO materials
            (project_id,description,group_name,item_type,material,source_page,
             length,drawing_length,wire_allowance_mm,radius_diam,quantity)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (self.project, 'ARAME GANCHO', 'Arame', 'materia_prima',
             'ARAME BTC CLARO Ø6', 'ARAME GANCHO.pdf#page=1',
             861, 841, 20, 6, 10))
        conn.commit()
        conn.close()
        result = ai_pdf_review.normalize_response({'items': [{
            'description': 'ARAME GANCHO', 'item_type': 'materia_prima',
            'material': 'ARAME BTC CLARO Ø6', 'length': 841,
            'radius_diam': 6, 'quantity': 1, 'quantity_scope': 'local_table',
            'dimension_basis': 'corte', 'evidence': 'COMPRIMENTO 841 Ø6'}]})
        ai_pdf_review.save_review(self.project, 'ARAME GANCHO.pdf', 1,
                                  pdf_path, result, ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        conn.execute('''INSERT INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force)
            VALUES (?,?,1,?,'done',1,0,0)''',
            (self.project, 'ARAME GANCHO.pdf', ai_pdf_review.AUTO_MODEL))
        conn.commit()
        conn.close()
        preview = preview_pending_ai_dimensions(self.project)
        self.assertEqual(preview['new_ai_items'], 0)
        self.assertEqual(preview['unlinked_ai_items'], 0)

    def test_existing_acrylic_bought_is_not_staged_as_extra_steel(self):
        from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions

        pdf_path = self.source / 'LOGO.pdf'
        pdf = canvas.Canvas(str(pdf_path))
        pdf.drawString(50, 700, 'LOGO 650 x 182,87 x 6 Chapa Acrilico')
        pdf.save()
        conn = database.get_connection()
        conn.execute('''INSERT INTO materials
            (project_id,description,group_name,item_type,material,source_page,
             length,width,thickness,quantity)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (self.project, 'LOGO BRAHMA FRONTAL', 'Polímero/PSAI', 'comprado',
             'Chapa Acrílico', 'LOGO.pdf#page=1', 650, 182.87, 6, 2))
        conn.commit()
        conn.close()
        result = ai_pdf_review.normalize_response({'items': [{
            'description': 'LOGO BRAHMA FRONTAL', 'item_type': 'materia_prima',
            'material': 'Chapa Acr�lico', 'length': 650, 'width': 182.87,
            'thickness': 6, 'quantity': 2, 'quantity_scope': 'local_table',
            'dimension_basis': 'corte',
            'evidence': 'ITEM 09, Chapa Acrílico 650 x 182,87 x 6'}]})
        ai_pdf_review.save_review(self.project, 'LOGO.pdf', 1, pdf_path,
                                  result, ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        conn.execute('''INSERT INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force)
            VALUES (?,?,1,?,'done',1,0,0)''',
            (self.project, 'LOGO.pdf', ai_pdf_review.AUTO_MODEL))
        conn.commit()
        conn.close()
        self.assertEqual(preview_pending_ai_dimensions(self.project)['new_ai_items'], 0)
        self.assertEqual(apply_pending_ai_dimensions(self.project)['new_ai_items'], 0)

    def test_ai_only_stage_ignores_same_part_in_another_pdf_and_mixed_material(self):
        from ai_bulk_dimensions import preview_pending_ai_dimensions

        pdf_path = self.source / 'another.pdf'
        pdf = canvas.Canvas(str(pdf_path))
        pdf.drawString(50, 700, 'Outra folha')
        pdf.save()
        result = ai_pdf_review.normalize_response({'items': [
            {'description': 'PSAI FR. Display', 'item_type': 'comprado',
             'material': 'PSAI BRANCO #1mm', 'length': 299, 'width': 234,
             'thickness': 1, 'dimension_basis': 'corte',
             'evidence': 'Tabela: 299 x 234 x 1 mm'},
            {'description': 'Material composto', 'item_type': 'materia_prima',
             'material': 'TUBO QUAD. 20x20 / ARAME BTC Ø6',
             'length': 400, 'radius_diam': 6, 'dimension_basis': 'corte',
             'evidence': 'TUBO e ARAME separados no desenho'}]})
        ai_pdf_review.save_review(self.project, 'another.pdf', 1, pdf_path,
                                  result, ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        conn.execute('''INSERT INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force)
            VALUES (?,?,1,?,'done',1,0,0)''',
            (self.project, 'another.pdf', ai_pdf_review.AUTO_MODEL))
        conn.commit()
        conn.close()
        self.assertEqual(preview_pending_ai_dimensions(self.project)['new_ai_items'], 0)
