"""The company audit must reject mutations before reaching a network file."""
import os
import unittest

from company_coverage_audit import (DEFAULT_OUTPUT, local_output, project_key,
                                    reject_network_mutation, role)


class CompanyAuditSafetyTests(unittest.TestCase):
    def test_network_read_allowed_but_write_update_and_create_denied(self):
        path = r'\\192.168.1.3\bluelight\CLIENTE\desenho.pdf'
        reject_network_mutation('open', (path, 'r', os.O_RDONLY))
        for mode, flags in [('w', os.O_WRONLY), ('r+', os.O_RDWR),
                            ('x', os.O_CREAT), (None, os.O_TRUNC)]:
            with self.subTest(mode=mode, flags=flags):
                with self.assertRaises(PermissionError):
                    reject_network_mutation('open', (path, mode, flags))

    def test_network_metadata_changes_move_delete_and_database_are_denied(self):
        path = r'\\192.168.1.3\bluelight\CLIENTE\original.pdf'
        for event, args in [('os.remove', (path,)), ('os.utime', (path, None)),
                            ('os.rename', (path, 'C:/copiado.pdf')),
                            ('os.rename', ('C:/local.pdf', path)),
                            ('sqlite3.connect', (path,))]:
            with self.subTest(event=event, args=args):
                with self.assertRaises(PermissionError):
                    reject_network_mutation(event, args)

    def test_output_is_local_and_package_boundary_preserves_production_parent(self):
        self.assertEqual(local_output(DEFAULT_OUTPUT), DEFAULT_OUTPUT.resolve())
        with self.assertRaises(ValueError):
            local_output(r'\\192.168.1.3\bluelight\auditoria')
        self.assertEqual(project_key({'path':'RISE/CLIENTE/DISPLAY/PROJETO/BASE/CHAPA.pdf'}),
                         'RISE/CLIENTE/DISPLAY')
        self.assertEqual(role('RISE/CLIENTE/DISPLAY/!OBSOLETO/PROJETO/a.pdf'), 'obsolete')
        self.assertEqual(role('RISE/CLIENTE/DISPLAY/ORÇAMENTO/historico.pdf'), 'budget')


if __name__ == '__main__':
    unittest.main()
