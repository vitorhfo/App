"""Checks the prices confirmed from the blank cost model."""
import sqlite3

from pricing import metal_price_basis, price_item


conn=sqlite3.connect(':memory:')
conn.row_factory=sqlite3.Row
conn.execute('''CREATE TABLE catalog_prices (
    id INTEGER PRIMARY KEY, description TEXT, normalized TEXT, value REAL,
    unit TEXT, source TEXT, approved INTEGER)''')
conn.executemany('INSERT INTO catalog_prices VALUES (?,?,?,?,?,?,?)',[
    (1,'TUBO QUADRADO 25X25X0,9MM','TUBO QUADRADO 25X25X0.9MM',8.0,'kg','Comprados / Tubos',1),
    (2,'TUBO QUADRADO 20X20X0,9MM','TUBO QUADRADO 20X20X0.9MM',7.74,'kg','Comprados / Tubos',1),
    (3,'TUBO RETANGULAR 50X30X2,0MM','TUBO RETANGULAR 50X30X2.0MM',11.3,'kg','Comprados / Tubos',1),
    (4,'TUBO RETANGULAR 50X30X2,65MM','TUBO RETANGULAR 50X30X2.65MM',12.2,'kg','Comprados / Tubos',1),
    (5,"TUBO REDONDO 5/8' X 0,9MM","TUBO REDONDO 5/8 X 0.9MM",11.91,'kg','Comprados / Tubos',1),
    (6,"TUBO REDONDO 5/8' X 1,2MM","TUBO REDONDO 5/8 X 1.2MM",16.3,'kg','Comprados / Tubos',1),
])
rules={'mp_chapa_aco':7.02,'mp_arame':6.34,'mp_arame_fator_liquido':78.75,
       'mp_tubo_acrescimo_ipi':3.25,'mp_tubo_fator_liquido':78.75}


def item(description,group,material,weight,**kwargs):
    return dict(description=description,group_name=group,material=material,
                item_type='materia_prima',unit_weight=weight,unit_area=0,
                thickness=kwargs.get('thickness',0),width=kwargs.get('width',0),
                depth=kwargs.get('depth',0),radius_diam=0,printing='0x0',length=0,unit='un')


tube=item('TUBO PEZINHOS','Tubo Quadrado/Retangular','TUBO QUAD. ACO 25 X 25 X 0.90MM',
          0.28,width=25,depth=25,thickness=0.9)
assert metal_price_basis(tube,rules,conn)['rate']==8.0
assert price_item(tube,rules,conn)[0]==round(0.28*8*1.0325*0.7875,4)
rounded=item('POSTE','Tubo Quadrado/Retangular','TUBO IND 50 X 30 X 1,5MM',2.0,
             width=50,depth=30,thickness=1.5)
basis=metal_price_basis(rounded,rules,conn)
assert basis['rate']==11.3 and basis['thickness_used']==2.0
assert 'esp 1.5→2 mm' in basis['source']
assert price_item(rounded,rules,conn)[0]==round(2*11.3*1.0325*0.7875,4)
assert metal_price_basis(dict(rounded,thickness=2.1),rules,conn)['thickness_used']==2.65
assert metal_price_basis(dict(rounded,thickness=2.66),rules,conn) is None
round_tube=dict(rounded,group_name='Tubo Redondo',material='TUBO RED. 5/8 x 1,0mm',
                radius_diam=15.9,thickness=1.0,width=0,depth=0)
assert metal_price_basis(round_tube,rules,conn)['thickness_used']==1.2
assert price_item(item('CHAPA BASE','Chapa','AÇO CARBONO',1),rules,conn)[0]==7.02
assert price_item(item('CH APARADOR BASE','Chapa','CHAPA F.F. SAE 1008',0.00148),rules,conn)[0]==round(0.00148*7.02,4)
assert price_item(item('ARAME GANCHO','Arame','ARAME BTC CLARO',1),rules,conn)[0]==round(6.34*0.7875,4)
assert price_item(item('TUBO DESCONHECIDO','Tubo Quadrado/Retangular','AÇO',1,
                       width=99,depth=99,thickness=0.9),rules,conn)[0] is None
bought=dict(tube,item_type='comprado')
assert metal_price_basis(bought,rules,conn) is None
assert price_item(bought,rules,conn)[0] is None
print('Preços de tubo, chapa, arame e perfis sem correspondência: OK')
