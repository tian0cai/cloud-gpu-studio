import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

SCRIPT = Path(__file__).resolve().parents[1] / 'outputs/cloud-gpu-studio/download_models.py'


class DownloadModelsTests(unittest.TestCase):
    def test_pinned_xet_download_is_verified_and_reused(self):
        payload = b'pinned model bytes'
        item = {
            'repo': 'org/model', 'revision': 'a' * 40,
            'filename': 'vae/weights.safetensors',
            'destination': 'vae/renamed.safetensors',
            'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
        }
        def fake_hub_download(*, repo_id, filename, revision, local_dir):
            self.assertEqual((repo_id, filename, revision),
                             (item['repo'], item['filename'], item['revision']))
            source = local_dir / filename
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(payload)
            return str(source)
        hub = types.ModuleType('huggingface_hub')
        hub.hf_hub_download = Mock(side_effect=fake_hub_download)
        old_hub = sys.modules.get('huggingface_hub')
        sys.modules['huggingface_hub'] = hub
        try:
            spec = importlib.util.spec_from_file_location('download_models_test', SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = root / 'manifest.json'
                manifest.write_text(json.dumps({'files': [item]}))
                module.main(manifest, root)
                module.main(manifest, root)
                self.assertEqual((root / item['destination']).read_bytes(), payload)
                hub.hf_hub_download.assert_called_once()
                (root / item['destination']).unlink()
                incomplete_dir = (module.staging_path(item, root) / '.cache/huggingface/download/vae')
                incomplete_dir.mkdir(parents=True, exist_ok=True)
                (incomplete_dir / 'chunk.incomplete').write_bytes(payload[:8])
                self.assertEqual(module.downloaded_bytes(item, root), 8)
        finally:
            if old_hub is None:
                del sys.modules['huggingface_hub']
            else:
                sys.modules['huggingface_hub'] = old_hub


if __name__ == '__main__':
    unittest.main()
