"""Checks PSAI rates and printing directly against the CONTROLV workbook."""
import sqlite3

from controlv import controlv_psai_rows
from pricing import price_item, psai_price_basis

rows=controlv_psai_rows()
assert rows['pl_psai_branco_10']==(29.4,'CONTROLV!D4')
assert rows['pl_psai_leitoso_100']==(115.0,'CONTROLV!D10')
assert rows['imp_digital_face']==(25.0,'CONTROLV!N4')
assert rows['imp_psai_adicional_4x1']==(10.0,'CONTROLV!K4')
conn=sqlite3.connect(':memory:')
conn.row_factory=sqlite3.Row
conn.execute('CREATE TABLE price_rules (rule_key TEXT, source TEXT)')
conn.executemany('INSERT INTO price_rules VALUES (?,?)',[(key,source) for key,(_,source) in rows.items()])
rules={key:value for key,(value,_) in rows.items()}


def item(material,thickness=1.0,printing='0x0'):
    return {'item_type':'comprado','group_name':'Polímero/PSAI','description':'PEÇA PSAI',
            'material':material,'thickness':thickness,'unit_area':0.181,
            'printing':printing,'unit_weight':0,'unit':'un','length':0}


white=item('PSAI BRANCO 1MM')
assert psai_price_basis(white,rules,conn)['source']=='CONTROLV!D4'
assert price_item(white,rules,conn)[0]==round(0.181*29.4,4)
assert price_item(item('PSAI BRANCO 1MM',printing='4x0'),rules,conn)[0]==round(0.181*(29.4+25),4)
assert price_item(item('PSAI BRANCO 1MM',printing='4x4'),rules,conn)[0]==round(0.181*(29.4+50),4)
colored=item('PSAI VERMELHO',thickness=1.5)
colored['unit_area']=0
colored['width']=264
colored['length']=558.5
assert price_item(colored,rules,conn)[0]==round(264*558.5/1_000_000*44*1.1,4)
assert psai_price_basis(item('PSAI SEM COR'),rules,conn) is None
rounded=psai_price_basis(item('PSAI BRANCO',thickness=0.9),rules,conn)
assert rounded['thickness_used']==1.0 and rounded['rate']==29.4
assert psai_price_basis(item('PSAI BRANCO',thickness=1.1),rules,conn)['thickness_used']==1.5
assert psai_price_basis(item('PSAI BRANCO',thickness=2.1),rules,conn) is None
assert psai_price_basis(item('PSAI CRISTAL',thickness=1.9),rules,conn)['thickness_used']==2.0
assert psai_price_basis(item('PSAI BRANCO',printing='4x1'),rules,conn) is None
assert psai_price_basis(item('PSAI BRANCO',printing='1x0'),rules,conn) is None
print('PSAI da CONTROLV e impressão por face: OK')
