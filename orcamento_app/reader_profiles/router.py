"""Explicit layout precedence shared by page and project readers.

Recognition stays inside each layout reader. A reader only wins after it
produces rows; a client name or a generic word such as MATERIAL never selects it.
"""
from dataclasses import dataclass, field

from .technical import (ordered_rise_grid_bom, compact_rise_cut_bom,
                        technical_grid_bom, technical_text_bom)


PROFILE_LABELS = {
    'technical_ordered_grid': 'Lista técnica com colunas identificadas',
    'technical_compact_cut': 'Quadro compacto de cortes',
    'technical_14_grid': 'Lista técnica de 14 colunas',
    'technical_text': 'Lista técnica em texto, sem grade reconhecida',
    'cad': 'Lista CAD com descrição e quantidade',
    'cad_part_number': 'Lista CAD com número da peça, descrição e quantidade',
    'cad_named_grid': 'Lista CAD por colunas de quantidade, componente e material',
    'rise_text': 'Lista de materiais RISE em texto',
    'outpromo': 'Lista de sete colunas',
    'score': 'Pacote SCORE com lista e cortes',
    'scanned_rise': 'Lista RISE digitalizada com colunas identificadas',
    'scanned_technical': 'Lista digitalizada da página 2',
    'cut_table': 'Quadro de corte de peça avulsa',
    'unrecognized': 'Formato não reconhecido',
}


@dataclass
class TableReading:
    profile: str = 'unrecognized'
    rows: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    reason: str = 'Nenhuma lista técnica reconhecida nesta página.'


def read_technical_table(text, page=None):
    """Keep the established precedence while preserving multiple grids per page."""
    if page is not None:
        sections = ordered_rise_grid_bom(page, separate=True)
        if sections:
            return TableReading('technical_ordered_grid',
                                [row for rows, _, _ in sections for row in rows], sections,
                                'Cabeçalho, ordem das colunas e células da grade reconhecidos.')
        for profile, reader, reason in (
            ('technical_compact_cut', compact_rise_cut_bom,
             'Cabeçalho compacto de sete colunas, sem colunas da lista completa.'),
            ('technical_14_grid', technical_grid_bom,
             'Células da lista de 14 colunas reconhecidas, incluindo campos vazios.'),
        ):
            rows = reader(page)
            if rows:
                return TableReading(profile, rows, reason=reason)
    rows = technical_text_bom(text)
    if rows:
        return TableReading('technical_text', rows,
                            reason='Cabeçalho ITEM/QTD/DESCRIÇÃO e linhas técnicas em texto.')
    return TableReading()


def technical_table_bom(text, page=None):
    """Compatibility entry point used by existing scripts and integrations."""
    return read_technical_table(text, page).rows


def record_reading(data, source, profile, rows=0, *, stage='recognized', reason=''):
    event = dict(source_page=source, profile=profile,
                 label=PROFILE_LABELS.get(profile, profile), rows=rows,
                 stage=stage, reason=reason)
    data.setdefault('reading_report', {'version': 1, 'events': []})['events'].append(event)
