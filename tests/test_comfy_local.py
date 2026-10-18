import importlib.util
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'outputs' / 'cloud-gpu-studio' / 'comfy_local.py'
SPEC = importlib.util.spec_from_file_location('comfy_local', SOURCE)
comfy_local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comfy_local)


class LocalComfySafetyTests(unittest.TestCase):
    def test_workflow_templates_install_without_overwriting_user_edits(self):
        with tempfile.TemporaryDirectory() as root:
            previous = comfy_local.COMFY
            comfy_local.COMFY = Path(root)
            try:
                comfy_local.install_workflows()
                folder = comfy_local.COMFY / 'user' / 'default' / 'workflows'
                single = folder / 'H3-单图首帧-FL2VA.json'
                dual = folder / 'H3-双图参考-Ref2VA.json'
                self.assertTrue(single.is_file())
                self.assertTrue(dual.is_file())
                single.write_text('my edited workflow')
                comfy_local.install_workflows()
                self.assertEqual(single.read_text(), 'my edited workflow')
            finally:
                comfy_local.COMFY = previous

    def test_install_refuses_unrelated_existing_directory(self):
        with tempfile.TemporaryDirectory() as root:
            previous = comfy_local.COMFY
            comfy_local.COMFY = Path(root)
            try:
                with self.assertRaisesRegex(RuntimeError, '不是 ComfyUI'):
                    comfy_local.install()
            finally:
                comfy_local.COMFY = previous

    def test_update_refuses_non_official_installation(self):
        with tempfile.TemporaryDirectory() as root:
            previous = comfy_local.COMFY
            comfy_local.COMFY = Path(root)
            (comfy_local.COMFY / 'main.py').write_text('')
            try:
                with self.assertRaisesRegex(RuntimeError, '官方 Git 仓库'):
                    comfy_local.update()
            finally:
                comfy_local.COMFY = previous


if __name__ == '__main__':
    unittest.main()
