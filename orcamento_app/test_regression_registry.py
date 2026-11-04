"""Keep every recorded regression connected to a runnable protection."""

from pathlib import Path
import ast
import re
import unittest


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'REGRESSOES.md'
ENTRY = re.compile(r'^\s*\|?\s*(R\d{2,3})\s*(?:\||—)')
TEST_FILE = re.compile(r'\b(test_[A-Za-z0-9_]+\.py)\b')
TEST_REFERENCE = re.compile(
    r'\b(test_[A-Za-z0-9_]+\.py)(?:::(\w+))?(?:::(\w+))?'
)


class RegressionRegistryTests(unittest.TestCase):
    def test_all_recorded_regressions_have_existing_protection(self):
        lines = REGISTRY.read_text(encoding='utf-8').splitlines()
        entries = {}
        for line in lines:
            match = ENTRY.match(line)
            if match:
                entries[match.group(1)] = line

        self.assertGreaterEqual(len(entries), 78)
        highest = max(int(regression_id[1:]) for regression_id in entries)
        self.assertEqual(
            set(entries),
            {f'R{number:02d}' for number in range(1, highest + 1)},
            'The regression register must not have missing or duplicate IDs.',
        )

        for regression_id, line in entries.items():
            test_files = TEST_FILE.findall(line)
            if regression_id == 'R63':
                # This is a documented unresolved reconciliation, not a fixed
                # parser behavior; retain its evidence and pending state.
                self.assertIn('pendente', line.lower())
                self.assertTrue(
                    (ROOT / 'data' / 'audits' / 'compare_rise_samples.py').is_file()
                )
                continue

            self.assertTrue(test_files, f'{regression_id} has no test reference')
            for filename in test_files:
                self.assertTrue((ROOT / filename).is_file(),
                                f'{regression_id} references missing test file {filename}')

            for filename, class_name, method_name in TEST_REFERENCE.findall(line):
                if not method_name:
                    continue
                tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
                classes = {node.name for node in ast.walk(tree)
                           if isinstance(node, ast.ClassDef)}
                methods = {node.name for node in ast.walk(tree)
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                self.assertIn(method_name, methods,
                              f'{regression_id} references missing test {method_name}')
                if class_name:
                    self.assertIn(class_name, classes,
                                  f'{regression_id} references missing test class {class_name}')


if __name__ == '__main__':
    unittest.main()
