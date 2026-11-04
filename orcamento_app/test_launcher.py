"""The desktop shortcut must start the copy used by the audited projects."""

from pathlib import Path
import unittest


class LauncherTest(unittest.TestCase):
    def test_desktop_launcher_points_to_current_app(self):
        app_root = Path(__file__).resolve().parents[2]
        launcher = app_root / 'iniciar_orcamento.bat'
        if not launcher.is_file():
            self.skipTest('Atalho da instalação local indisponível')
        text = launcher.read_text(encoding='ascii').lower().replace('/', '\\')
        self.assertIn('%~dp0arquivos_raw\\orcamento_app\\run_app.bat', text)


if __name__ == '__main__':
    unittest.main()
