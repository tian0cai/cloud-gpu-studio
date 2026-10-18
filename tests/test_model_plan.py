import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'outputs/cloud-gpu-studio/app_config.py'
OFFICIAL = ROOT / 'outputs/cloud-gpu-studio/models.lock.json'


class ModelPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        previous = os.environ.get('CLOUD_GPU_STUDIO_WORK_DIR')
        os.environ['CLOUD_GPU_STUDIO_WORK_DIR'] = str(self.work)
        self.addCleanup(self.restore_env, previous)
        spec = importlib.util.spec_from_file_location('app_config_under_test', CONFIG)
        self.config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.config)
        official = json.loads(OFFICIAL.read_text())['files']
        local = []
        mapping = {'qwen': {}, 'h3': {}}
        for file in official:
            item = dict(file)
            directory, name = item['destination'].split('/', 1)
            item['destination'] = directory + '/local-' + name
            item['size'] += 1
            item['sha256'] = 'a' * 64
            local.append(item)
            if directory == 'diffusion_models':
                role = 'unet'
            elif directory == 'text_encoders':
                role = 'clip'
            elif directory == 'vae' and item['preset'] == 'h3':
                role = 'audio_vae' if 'audio' in name else 'video_vae'
            else:
                role = 'vae'
            mapping[item['preset']][role] = Path(item['destination']).name
        (self.work / 'local.lock.json').write_text(json.dumps({'files': local}))
        (self.work / 'model-overrides.json').write_text(json.dumps({
            'model_manifest': 'local.lock.json', **mapping}))

    def restore_env(self, previous):
        if previous is None:
            os.environ.pop('CLOUD_GPU_STUDIO_WORK_DIR', None)
        else:
            os.environ['CLOUD_GPU_STUDIO_WORK_DIR'] = previous

    def selected(self, image, video):
        self.config.write({'provider': 'vast', 'image_model': image,
                           'video_model': video, 'video_mode': 'fl2va',
                           'custom_model': None})
        return json.loads(self.config.manifest().read_text())['files']

    def test_local_image_and_official_video_are_combined(self):
        files = self.selected('local-qwen', 'h3')
        self.assertEqual(len(files), 7)
        self.assertTrue(all(Path(f['destination']).name.startswith('local-')
                            for f in files if f['preset'] == 'qwen'))
        self.assertTrue(all(not Path(f['destination']).name.startswith('local-')
                            for f in files if f['preset'] == 'h3'))

    def test_full_local_pack_and_missing_component(self):
        files = self.selected('local-qwen', 'local-h3')
        self.assertEqual(len(files), 7)
        overrides = json.loads((self.work / 'model-overrides.json').read_text())
        overrides['h3']['clip'] = 'missing.safetensors'
        (self.work / 'model-overrides.json').write_text(json.dumps(overrides))
        with self.assertRaisesRegex(ValueError, 'clip'):
            self.config.manifest()

    def test_legacy_combined_setting_is_read_as_two_slots(self):
        (self.work / 'app-settings.json').write_text(json.dumps({'provider': 'vast', 'model': 'local'}))
        settings = self.config.read()
        self.assertEqual((settings['image_model'], settings['video_model']),
                         ('local-qwen', 'local-h3'))

    def test_reference_mode_downloads_its_checkpoint_first_and_skips_fl2va_unet(self):
        self.config.write({'provider': 'vast', 'image_model': 'local-qwen',
                           'video_model': 'local-h3', 'video_mode': 'ref2va',
                           'custom_model': None})
        files = json.loads(self.config.manifest().read_text())['files']
        self.assertEqual(len(files), 7)
        self.assertEqual([f['preset'] for f in files].count('h3-ref2va'), 1)
        self.assertEqual(files[0]['size'], 20970379616)
        self.assertFalse(any('fl2va' in f['destination'] for f in files))
        self.assertEqual([f['preset'] for f in files[1:4]], ['h3'] * 3)

    def test_active_reference_switch_requires_current_machine_download(self):
        self.selected('local-qwen', 'local-h3')
        (self.work / 'active-provider.json').write_text('{"provider":"vast"}')
        (self.work / 'vast-deployment.json').write_text('{"id":123}')
        settings = self.config.read()
        with self.assertRaisesRegex(ValueError, 'Download and verify'):
            self.config.write({**settings, 'video_mode': 'ref2va'})
        (self.work / 'ref2va-ready.json').write_text('{"provider":"vast","id":"123"}')
        self.config.write({**settings, 'video_mode': 'ref2va'})
        self.assertTrue(self.config.public_settings()['ref2va_ready'])
        with self.assertRaisesRegex(ValueError, 'FL2VA'):
            self.config.write({**settings, 'video_mode': 'fl2va'})
        (self.work / 'fl2va-ready.json').write_text('{"provider":"vast","id":"123"}')
        self.config.write({**settings, 'video_mode': 'fl2va'})
        self.assertTrue(self.config.public_settings()['fl2va_ready'])


if __name__ == '__main__':
    unittest.main()
