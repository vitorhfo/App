"""Regression checks for the three PDF layouts in the José Vitor collection."""
from pathlib import Path

from app import jose_vitor_source_folders
from reader_v3 import process_complete_project


folders=jose_vitor_source_folders()
assert len(folders)==12, len(folders)
by_name={x['name'].upper():Path(x['path']) for x in folders}

technical=process_complete_project(by_name['ALPA BASICO 2X5'])
assert len(technical['materials'])==22
assert any(x['description']=='TUBO PEZINHOS' and x['quantity']==2
           for x in technical['materials'])
assert any(x['description']=='SM LATERAL ESQUERDA' and x['is_inferred']
           and 'espelhada' in x['observation'] for x in technical['materials'])
assert sum(x['parent_assembly'].endswith('SM LATERAL DIREITA')
           and x['quantity']>=2 for x in technical['materials'])==6
assert any(x['item_type']=='subconjunto' and x['group_name']=='Subconjunto'
           for x in technical['materials'])
assert all(x['item_type'] in ('materia_prima','comprado','subconjunto')
           for x in technical['materials'])

cad=process_complete_project(by_name['DISPLAY DE CHAO TAMBASA'])
assert len(cad['materials'])>=25
assert any(x['quantity']==30 and x['description'].startswith('ARAME GANCHO')
           for x in cad['materials'])
assert any(x['title']=='Nomes divergentes entre lista e desenhos'
           for x in cad['pending_decisions'])

scan=process_complete_project(by_name['ALPA BASICO 3X4'])
assert len(scan['materials'])>=12
assert any(x['title']=='Lista extraída por OCR' for x in scan['pending_decisions'])
assert any(x['unit']=='?' for x in scan['materials'])

for project in (technical,cad,scan):
    assert all(x['source_page'] for x in project['materials'])
    assert all(x['unit_price'] is None for x in project['materials'])
print('José Vitor: lista técnica, CAD e PDF digitalizado lidos como preliminares.')
