"""User-confirmed physical additions for one immutable SCORE drawing revision.

These are budget annotations, not measurements inferred from the PDF. A new
revision hash must be reviewed before carrying them forward.
"""

import hashlib


BRAHMA_PDF_SHA256 = '829a0ce39b63f9293feeb9f0a8b4230ab3ba05a8dada9271d6d66427c1651de2'


def confirmed_brahma_additions(path):
    with open(path, 'rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != BRAHMA_PDF_SHA256:
        return []
    # On 21/10/2026 the user confirmed these as separate physical parts:
    # the second side-closing pair and the steel cover over the testeria.
    return [
        dict(description='FECHAMENTO LATERAL ADICIONAL DA ESTRUTURA',
             drawing_id='BRAHMA_ORCAMENTO_MANUAL: FECHAMENTO LATERAL 2',
             parent='CONJUNTO ESTRUTURA METALICA', quantity=2,
             length=2359, width=159, thickness=.7,
             source='CÁLCULO+N. -2.xls, Total!29',
             note='Par distinto do FECHAMENTO FRONTAL/TRASEIRO do PDF.'),
        dict(description='TAMPA DE AÇO SOBRE A ESTRUTURA DA TESTEIRA',
             drawing_id='BRAHMA_ORCAMENTO_MANUAL: TAMPA TESTEIRA',
             parent='ESTRUTURA DA TESTEIRA', quantity=1,
             length=1250, width=520, thickness=3,
             source='CÁLCULO+N. - AMB_2239_25_BRAHMA_ILHA.xls, Total!33',
             note='Peça de aço distinta do FECHAMENTO SUPERIOR PSAI comprado.'),
    ]


def confirmed_brahma_reinforcements(path):
    with open(path, 'rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != BRAHMA_PDF_SHA256:
        return {}
    # The finished CÁLCULO separates each welded reinforcement into one
    # 25x25 tube and two steel blanks. Wall gauges/flat blanks come from that
    # quote; the PDF independently shows tube length, section and plate span.
    return {
        'AMB_2239_25_03_PRT_21': [
            ('tubo', 417, 25, 25, 1.2, 'CÁLCULO+N. - AMB_2239_25_BRAHMA_ILHA.xls:Total!17'),
            ('chapa inferior', 150, 60, 0, 1, 'CÁLCULO+N. - AMB_2239_25_BRAHMA_ILHA.xls:Total!31'),
            ('chapa superior dobrada', 90, 60, 0, 1, 'CÁLCULO+N. - AMB_2239_25_BRAHMA_ILHA.xls:Total!32'),
        ],
        'AMB_2239_25_03_PRT_22': [
            ('tubo', 317, 25, 25, 1.2, 'CÁLCULO+N. - AMB_2239_25_BRAHMA_ILHA.xls:Total!18'),
            ('chapa inferior', 150, 60, 0, 1, 'CÁLCULO+N. - AMB_2239_25_BRAHMA_ILHA.xls:Total!31'),
            ('chapa superior dobrada', 90, 60, 0, 1, 'CÁLCULO+N. - AMB_2239_25_BRAHMA_ILHA.xls:Total!32'),
        ],
    }


def confirmed_brahma_sheet_cut(path):
    with open(path, 'rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != BRAHMA_PDF_SHA256:
        return {}
    # PRT_06, cut-table row 3 says "Sheet", QTD 2. The drawing shows
    # 80 x 50 mm tabs and a 3 mm section; the finished CÁLCULO confirms it.
    return {'AMB_2239_25_03_PRT_06: corte 3':
            {'length': 80, 'width': 50, 'thickness': 3,
             'source': 'CÁLCULO+N. -2.xls:Total!31'}}
