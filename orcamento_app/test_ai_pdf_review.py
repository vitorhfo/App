"""The visual reviewer is independent of saved and manually edited materials."""

import io
import json
import urllib.error
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from ai_pdf_review import (compare_review, normalize_response, page_payload,
                           request_google, resolve_pdf, load_review, save_review,
                           _cache_file, validate_model, MODEL_OPTIONS,
                           ProviderRateLimitError)
from config import DATA_DIR


DURACELL = (Path(__file__).resolve().parent.parent.parent / 'DADOS' / 'JOSÉ VITOR' /
            'TESTES DE ORÇAMENTO' / 'FLAVIO PAPILE' / 'Display Balcão DURACELL' /
            'PROJETO')


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class AiPdfReviewTest(unittest.TestCase):
    def test_same_page_drawing_code_disambiguates_equal_descriptions(self):
        # DOCILE RDS007 puts the drawing code in the second BOM column.  The
        # parent may contain repeated descriptions for different physical parts.
        ai = normalize_response({'items': [{
            'item_number': '7', 'drawing_id': 'RDS007P10-01',
            'description': 'COMUNICACAO FRONTAL DA BASE', 'quantity': 4,
            'quantity_scope': 'local_table', 'length': 95}]})
        saved = [
            {'id': 41, 'description': 'COMUNICACAO FRONTAL DA BASE',
             'drawing_id': 'RDS007P11-01', 'length': 110, 'quantity': 2},
            {'id': 42, 'description': 'COMUNICACAO FRONTAL DA BASE',
             'drawing_id': 'RDS007P10-01', 'length': 95, 'quantity': 4},
        ]
        result = compare_review({'result': ai}, saved)
        self.assertEqual(result['comparisons'][0]['script_item_id'], 42)
        missing = compare_review({'result': ai}, [saved[0]])
        self.assertIsNone(missing['comparisons'][0]['script_item_id'])

    def test_score_page_keeps_revision_and_drawing_identity_without_merging_codes(self):
        ai = normalize_response({'items': [{
            'description': 'Estrutura Lateral', 'drawing_id': 'AMB_1902_24_07_PRT_11',
            'owner_assembly': 'AMB_1902_24_07_ASM_05', 'revision': '01',
            'quantity': 1, 'quantity_scope': 'local_table'}]})
        self.assertEqual(ai['items'][0]['owner_assembly'], 'AMB_1902_24_07_ASM_05')
        self.assertEqual(ai['items'][0]['revision'], '01')
        candidates = [
            {'id': 11, 'description': 'Estrutura Lateral', 'drawing_id': 'AMB_1902_24_07_PRT_11',
             'item_type': 'materia_prima'},
            {'id': 12, 'description': 'Estrutura Lateral', 'drawing_id': 'AMB_1902_24_07_PRT_12',
             'item_type': 'materia_prima'},
        ]
        rows = compare_review({'result': ai}, [], cross_page_items=candidates)['comparisons']
        self.assertEqual([row['script_item_id'] for row in rows], [11])
        cut = {**candidates[0], 'id': 13,
               'drawing_id': 'AMB_1902_24_07_PRT_11: corte 1'}
        rows = compare_review({'result': ai}, [], cross_page_items=[cut])['comparisons']
        self.assertEqual([row['script_item_id'] for row in rows], [13])

    def test_independent_review_marks_agreement_missing_cota_and_disagreement(self):
        saved = [{'id': 10, 'item_num': 1, 'description': 'PSAI LAT. Display Balcão DURACELL',
                  'length': 250, 'width': 0, 'thickness': 1, 'quantity': 2,
                  'unit_weight': .042}]
        before = [dict(row) for row in saved]
        ai = normalize_response({'drawing_title': 'PSAI LAT.', 'items': [
            {'item_number': '1', 'description': 'PSAI LAT. Display Balcão DURACELL',
             'length': 250, 'width': 150, 'thickness': 1, 'quantity': 1,
             'unit_weight_g': 42.3, 'dimension_basis': 'externa',
             'evidence': 'cotas 250 e 150 na vista frontal'}]})
        result = compare_review({'result': ai}, saved)
        self.assertEqual(result['comparisons'][0]['script_item_id'], 10)
        states = {field['field']: field['state'] for field in result['comparisons'][0]['fields']}
        self.assertEqual(states['length'], 'agree')
        self.assertEqual(states['width'], 'ai_only')
        self.assertEqual(states['quantity'], 'unverified')
        self.assertEqual(states['unit_weight_g'], 'agree')
        self.assertEqual(saved, before)

    def test_two_cut_rows_stay_separate_and_ambiguous_match_is_not_forced(self):
        ai = normalize_response({'items': [
            {'item_number': '1', 'description': 'TUBO IND 50 X 30 X 1,5mm', 'length': 1286, 'quantity': 1},
            {'item_number': '2', 'description': 'TUBO IND 50 X 30 X 1,5mm', 'length': 323, 'quantity': 1},
        ]})
        saved = [{'id': 1, 'item_num': 1, 'description': 'TUBO IND 50 X 30', 'length': 1286},
                 {'id': 2, 'item_num': 2, 'description': 'TUBO IND 50 X 30', 'length': 323}]
        compared = compare_review({'result': ai}, saved)
        self.assertEqual([row['script_item_id'] for row in compared['comparisons']], [1, 2])
        ambiguous = compare_review({'result': {'items': [dict(ai['items'][0], item_number='')]}},
                                   [dict(saved[0], item_num=1), dict(saved[1], item_num=2)])
        self.assertIsNone(ambiguous['comparisons'][0]['script_item_id'])

    def test_other_page_of_same_pdf_matches_by_identity_not_local_row_number(self):
        ai = normalize_response({'items': [
            {'item_number': '1', 'description': 'TUBO VERTICAL FUNDO',
             'item_type': 'materia_prima', 'material': 'TUBO QUADRADO 25X25X0,9',
             'length': 1630, 'width': 25, 'depth': 25, 'thickness': .9,
             'quantity': 1, 'quantity_scope': 'project_total', 'unit_weight_g': 1110},
            {'item_number': '1', 'description': 'TUBO HORIZONTAL TESTEIRA',
             'item_type': 'materia_prima', 'material': 'TUBO QUAD. 20 X 20 X 0,90',
             'length': 275, 'width': 20, 'depth': 20, 'thickness': .9},
        ]})
        sibling_page = [
            {'id': 1601, 'item_num': 4, 'description': 'TUBO VERTICAL FUNDO',
             'item_type': 'materia_prima', 'group_name': 'Tubo Quadrado/Retangular',
             'length': 1630, 'width': 25, 'depth': 25, 'thickness': .9,
             'quantity': 2, 'unit_weight': 1.110138},
            {'id': 1602, 'item_num': 5, 'description': 'TUBO HORIZONTAL TESTEIRA',
             'item_type': 'materia_prima', 'group_name': 'Tubo Quadrado/Retangular',
             'length': 275, 'width': 20, 'depth': 20, 'thickness': .9},
        ]
        compared = compare_review({'result': ai}, [], cross_page_items=sibling_page)
        self.assertEqual([row['script_item_id'] for row in compared['comparisons']],
                         [1601, 1602])
        quantity = next(field for field in compared['comparisons'][0]['fields']
                        if field['field'] == 'quantity')
        self.assertEqual(quantity['state'], 'unverified')

    def test_other_page_rejects_same_name_with_conflicting_geometry(self):
        ai = normalize_response({'items': [
            {'description': 'TUBO VERTICAL FUNDO', 'item_type': 'materia_prima',
             'length': 1630, 'width': 25, 'depth': 25, 'thickness': .9}]})
        siblings = [
            {'id': 1, 'description': 'TUBO VERTICAL FUNDO', 'item_type': 'materia_prima',
             'group_name': 'Tubo Quadrado/Retangular', 'length': 1200, 'width': 25},
            {'id': 2, 'description': 'TUBO VERTICAL FUNDO', 'item_type': 'materia_prima',
             'group_name': 'Tubo Quadrado/Retangular', 'length': 0, 'width': 25},
        ]
        compared = compare_review({'result': ai}, [], cross_page_items=siblings)
        self.assertIsNone(compared['comparisons'][0]['script_item_id'])

    def test_other_page_does_not_match_a_tube_to_a_sheet(self):
        ai = normalize_response({'items': [{
            'description': 'BASE', 'item_type': 'materia_prima',
            'material': 'TUBO QUADRADO 25X25X0,9', 'length': 1630}]})
        sheet = [{'id': 3, 'description': 'BASE', 'item_type': 'materia_prima',
                  'group_name': 'Chapa', 'length': 0, 'width': 0}]
        compared = compare_review({'result': ai}, [], cross_page_items=sheet)
        self.assertIsNone(compared['comparisons'][0]['script_item_id'])

    def test_other_page_wire_compares_finished_cut_before_welding_allowance(self):
        ai = normalize_response({'items': [{
            'description': 'ARAME GANCHO', 'item_type': 'materia_prima',
            'material': 'ARAME BTC CLARO Ø 6', 'length': 841,
            'radius_diam': 6, 'quantity': 1, 'unit_weight_g': 180,
            'dimension_basis': 'corte', 'quantity_scope': 'local_table'}]})
        saved = {'id': 1609, 'description': 'ARAME GANCHO',
                 'item_type': 'materia_prima', 'group_name': 'Arame',
                 'length': 861, 'drawing_length': 841, 'wire_allowance_mm': 20,
                 'radius_diam': 6, 'quantity': 10, 'unit_weight': .191103,
                 'finished_unit_weight': .18}
        rows = compare_review({'result': ai}, [], cross_page_items=[saved])['comparisons']
        self.assertEqual(rows[0]['script_item_id'], 1609)
        states = {field['field']: field['state'] for field in rows[0]['fields']}
        self.assertEqual(states['length'], 'agree')
        self.assertEqual(states['unit_weight_g'], 'agree')
        self.assertEqual(states['quantity'], 'unverified')
        self.assertIsNone(compare_review({'result': ai}, [],
            cross_page_items=[{**saved, 'drawing_length': 820,
                               'length': 840}])['comparisons'][0]['script_item_id'])

    def test_one_child_pdf_validates_both_saved_duracell_sides(self):
        ai = normalize_response({'items': [{'description': 'PSAI Lateral Display Balcão DURACELL',
                                                'length': 250, 'width': 150, 'thickness': 1,
                                                'quantity': 1}]})
        saved = [
            {'id': 762, 'item_num': 11, 'description': 'PSAI LAT. DIR Display Balcão DURACELL',
             'length': 250, 'width': 150, 'thickness': 1, 'quantity': 1},
            {'id': 763, 'item_num': 12, 'description': 'PSAI LAT. ESQ Display Balcão DURACELL',
             'length': 250, 'width': 150, 'thickness': 1, 'quantity': 1},
        ]
        compared = compare_review({'result': ai}, saved)
        self.assertEqual([row['script_item_id'] for row in compared['comparisons']], [762, 763])
        self.assertFalse(compared['script_only'])
        self.assertTrue(all(all(field['state'] == 'agree' for field in row['fields']
                                if field['field'] != 'quantity') for row in compared['comparisons']))

    def test_project_total_quantity_can_be_compared(self):
        ai = normalize_response({'items': [{'description': 'ARAME', 'quantity': 2,
                                                'quantity_scope': 'project_total'}]})
        compared = compare_review({'result': ai}, [{'id': 1, 'description': 'ARAME', 'quantity': 4}])
        quantity = next(field for field in compared['comparisons'][0]['fields'] if field['field'] == 'quantity')
        self.assertEqual(quantity['state'], 'different')

    def test_unlinked_pdf_reports_discovered_item_without_creating_material(self):
        ai = normalize_response({'items': [{'description': 'ARAME BTC Ø5',
                                                'length': 40, 'radius_diam': 5,
                                                'evidence': 'cotas 40 e Ø5 na vista'}]})
        compared = compare_review({'result': ai}, [])
        self.assertIsNone(compared['comparisons'][0]['script_item_id'])
        self.assertEqual({field['state'] for field in compared['comparisons'][0]['fields']}, {'ai_only'})
        self.assertEqual(compared['script_only'], [])

    def test_repeated_reckitt_part_matches_each_assembly_but_distinct_cuts_do_not(self):
        ai = normalize_response({'items': [{'description': 'PSAI SUPORTE Ilha Cash RECKITT',
                                                'length': 153.1, 'width': 120, 'thickness': 1}]})
        saved = [{'id': number, 'description': 'PSAI SUPORTE Ilha Cash RECKITT',
                  'length': 0, 'width': 0, 'thickness': 1} for number in (531, 579, 632, 680)]
        compared = compare_review({'result': ai}, saved)
        self.assertEqual([x['script_item_id'] for x in compared['comparisons']], [531, 579, 632, 680])
        different_cuts = [dict(saved[0], length=625), dict(saved[1], length=350)]
        self.assertIsNone(compare_review({'result': ai}, different_cuts)['comparisons'][0]['script_item_id'])

    def test_two_cut_rows_match_repeated_saved_movell_parts_by_cut_and_length(self):
        ai = normalize_response({'items': [
            {'item_number': '1', 'description': 'TUBO IND 50 X 30 X 1,5mm',
             'material': 'TUBO IND 50 X 30 X 1,5mm', 'length': 1286},
            {'item_number': '2', 'description': 'TUBO IND 50 X 30 X 1,5mm',
             'material': 'TUBO IND 50 X 30 X 1,5mm', 'length': 323},
        ]})
        saved = [
            {'id': 880, 'item_num': 24, 'description': 'TB. POSTE - corte 1: TUBO IND 50 X 30 X 1,5mm, 1286 mm',
             'material': 'TUBO IND 50 X 30 X 1,5mm', 'length': 1286},
            {'id': 909, 'item_num': 56, 'description': 'TB. POSTE - corte 1: TUBO IND 50 X 30 X 1,5mm, 1286 mm',
             'material': 'TUBO IND 50 X 30 X 1,5mm', 'length': 1286},
            {'id': 1348, 'item_num': 25, 'description': 'TB. POSTE - corte 2: TUBO IND 50 X 30 X 1,5mm, 323 mm',
             'material': 'TUBO IND 50 X 30 X 1,5mm', 'length': 323},
            {'id': 1351, 'item_num': 57, 'description': 'TB. POSTE - corte 2: TUBO IND 50 X 30 X 1,5mm, 323 mm',
             'material': 'TUBO IND 50 X 30 X 1,5mm', 'length': 323},
        ]
        compared = compare_review({'result': ai}, saved)
        self.assertEqual([x['script_item_id'] for x in compared['comparisons']],
                         [880, 909, 1348, 1351])
        self.assertFalse(compared['script_only'])
        self.assertTrue(all(next(field['state'] for field in row['fields']
                                 if field['field'] == 'length') == 'agree'
                            for row in compared['comparisons']))

    def test_google_request_uses_header_json_and_single_pdf_without_echoing_key(self):
        captured = {}

        def transport(request, timeout):
            captured['request'] = request
            captured['timeout'] = timeout
            return FakeResponse(json.dumps({'candidates': [{'content': {'parts': [
                {'text': json.dumps({'drawing_title': 'teste', 'items': [
                    {'description': 'Chapa', 'length': 250, 'width': 150}]})}
            ]}}]}).encode())

        result = request_google(b'%PDF-1.7\nteste', 'segredo-apenas-teste', transport)
        self.assertEqual(result['items'][0]['length'], 250)
        self.assertNotIn('segredo-apenas-teste', captured['request'].full_url)
        self.assertEqual(captured['request'].get_header('X-goog-api-key'), 'segredo-apenas-teste')
        body = json.loads(captured['request'].data)
        self.assertEqual(body['contents'][0]['parts'][1]['inline_data']['mime_type'], 'application/pdf')
        request_google(b'%PDF-1.7\nteste', 'segredo-apenas-teste', transport,
                       model='gemini-3.5-flash-lite')
        self.assertIn('/models/gemini-3.5-flash-lite:generateContent', captured['request'].full_url)

    def test_only_selected_free_models_and_separate_model_caches(self):
        self.assertEqual(set(MODEL_OPTIONS), {'gemini-3.8-flash', 'gemini-3.5-flash-lite',
                                             'gemini-3.1-flash-lite'})
        primary = _cache_file(12, 'desenho.pdf', 1)
        lite = _cache_file(12, 'desenho.pdf', 1, 'gemini-3.5-flash-lite')
        self.assertNotEqual(primary, lite)
        self.assertNotEqual(lite, _cache_file(12, 'desenho.pdf', 1, 'gemini-3.1-flash-lite'))
        self.assertEqual(primary, _cache_file(12, 'desenho.pdf', 1))
        with self.assertRaises(ValueError):
            validate_model('gemini-4-argon')
        from app import run_ai_pdf_review, AiPdfReviewRequest
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as raised:
            run_ai_pdf_review(12, AiPdfReviewRequest(path='desenho.pdf',
                                                     model='gemini-4-argon'))
        self.assertEqual(raised.exception.status_code, 400)

    def test_quota_period_is_detected_without_exposing_provider_response(self):
        def rate_error(quota_id):
            body = json.dumps({'error': {'message': 'Quota exceeded',
                                        'details': [{'quotaId': quota_id,
                                                     'secret': 'never-display'}]}}).encode()
            return urllib.error.HTTPError('https://generativelanguage.googleapis.com',
                                          429, 'Too Many Requests', {}, io.BytesIO(body))

        for quota_id, period in [('GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'day'),
                                 ('GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'minute')]:
            with self.subTest(period=period):
                with self.assertRaises(ProviderRateLimitError) as raised:
                    request_google(b'%PDF', 'test-key',
                                   transport=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                                       rate_error(quota_id)),
                                   model='gemini-3.5-flash-lite')
                self.assertEqual(raised.exception.period, period)
                self.assertNotIn('never-display', str(raised.exception))

    @unittest.skipUnless(DURACELL.is_dir(), 'Desenhos DURACELL indisponíveis')
    def test_real_duracell_child_page_and_path_safety(self):
        relative = 'PSAI Display Balcão DURACELL/PSAI LAT. Display Balcão DURACELL.PDF'
        path = resolve_pdf(DURACELL, relative)
        data, count = page_payload(path, 1)
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertEqual(count, 1)
        with self.assertRaises(ValueError):
            page_payload(path, 2)
        with self.assertRaises(ValueError):
            resolve_pdf(DURACELL, '../../outro.pdf')

    def test_cache_is_invalidated_when_original_pdf_changes(self):
        scratch = Path(DATA_DIR) / 'test_runs'
        scratch.mkdir(exist_ok=True)
        identity = uuid.uuid4().hex
        pdf = scratch / f'{identity}.pdf'
        cache = scratch / f'{identity}.json'
        self.assertTrue(pdf.resolve().is_relative_to(scratch.resolve()))
        try:
            with patch('ai_pdf_review._cache_file', return_value=cache):
                pdf.write_bytes(b'%PDF primeira versao')
                result = {'items': []}
                save_review(999999, 'desenho.pdf', 1, pdf, result)
                self.assertEqual(load_review(999999, 'desenho.pdf', 1, pdf)['result'], result)
                with patch('ai_pdf_review.PROMPT_HASH', 'new-prompt'):
                    self.assertIsNone(load_review(999999, 'desenho.pdf', 1, pdf))
                pdf.write_bytes(b'%PDF segunda versao com mais bytes')
                self.assertIsNone(load_review(999999, 'desenho.pdf', 1, pdf))
        finally:
            pdf.unlink(missing_ok=True)
            cache.unlink(missing_ok=True)

    def test_compact_prompt_keeps_review_from_equivalent_previous_prompt(self):
        scratch = Path(DATA_DIR) / 'test_runs'
        scratch.mkdir(exist_ok=True)
        identity = uuid.uuid4().hex
        pdf = scratch / f'{identity}.pdf'
        cache = scratch / f'{identity}.json'
        try:
            pdf.write_bytes(b'%PDF previous reviewed page')
            with patch('ai_pdf_review._cache_file', return_value=cache), \
                 patch('ai_pdf_review.PROMPT_HASH',
                       '21543a813b6fbe07ef6569af0ffcc74e87fe4e25dd0a3a51b5c1e69aad9f09de'):
                save_review(999999, 'desenho.pdf', 1, pdf, {'items': []})
            with patch('ai_pdf_review._cache_file', return_value=cache):
                self.assertIsNotNone(load_review(999999, 'desenho.pdf', 1, pdf))
        finally:
            pdf.unlink(missing_ok=True)
            cache.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
