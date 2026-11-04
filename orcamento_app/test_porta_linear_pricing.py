"""Porta-preço and porta-etiqueta share the approved per-meter rule."""
import sqlite3
import unittest

from pricing import porta_linear_length_mm, price_item
from calc_engine import resolve_material_group


class PortaLinearPricingTest(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('CREATE TABLE catalog_prices (id INTEGER, approved INTEGER, unit TEXT, normalized TEXT, value REAL)')
        self.rules={'acess_porta_etiqueta':6.8}

    def tearDown(self):
        self.conn.close()

    def bought(self,description,**fields):
        return {'item_type':'comprado','group_name':'Acessórios/Outros Comprados',
                'description':description,'material':'','length':0,'unit':'un',
                'unit_weight':0,'unit_area':0,'printing':'0x0',**fields}

    def test_explicit_lengths_use_same_rate(self):
        for description,length,expected in (
                ('PORTA ETIQUETA CRISTAL 550x55',550,3.74),
                ('PORTA PREÇO COM DUPLA FACE',64.7,0.44)):
            with self.subTest(description=description):
                item=self.bought(description,length=length)
                self.assertEqual(price_item(item,self.rules,self.conn)[0],expected)

    def test_length_from_label_or_alpa_material(self):
        label=self.bought('PORTA ETIQUETA SIMPLES 630 X 40')
        alpa=self.bought('PORTA PRECO COM DUPLA FACE',
                         material='PET CRISTAL 0,9MM 64.7 70')
        self.assertEqual(porta_linear_length_mm(label),630)
        self.assertEqual(porta_linear_length_mm(alpa),64.7)
        self.assertEqual(price_item(label,self.rules,self.conn)[0],4.284)
        self.assertEqual(price_item(alpa,self.rules,self.conn)[0],0.44)

    def test_no_length_and_wire_name_are_not_assumed(self):
        unknown=self.bought('PORTA PREÇO COM DUPLA FACE')
        wire=self.bought('PORTA ETIQ GANCHO',item_type='materia_prima',
                         group_name='Arame',length=70)
        self.assertEqual(porta_linear_length_mm(unknown),0)
        self.assertEqual(porta_linear_length_mm(wire),0)
        self.assertIsNone(price_item(unknown,self.rules,self.conn)[0])

    def test_porta_with_petg_still_uses_linear_rule(self):
        item=self.bought('PORTA PREÇO COM DUPLA FACE',group_name='Polímero/PSAI',
                         material='PETG CRISTAL 0,9MM',length=64.7,unit_area=0.2)
        self.assertEqual(resolve_material_group(item['description'],item['material']),
                         'Acessórios/Outros Comprados')
        self.assertEqual(price_item(item,self.rules,self.conn)[0],0.44)


if __name__=='__main__':
    unittest.main()
