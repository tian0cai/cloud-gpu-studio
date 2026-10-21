import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'outputs' / 'cloud-gpu-studio'
sys.path.insert(0, str(SCRIPTS))
import vultr_control


class VultrTests(unittest.TestCase):
    def test_catalog_filters_gpu_disk_price_and_lists_regions(self):
        plans = [
            {'id': 'vcg-a100', 'gpu_type': 'A100', 'gpu_vram_gb': 80,
             'disk': 200, 'hourly_cost': 2.5, 'locations': ['ewr', 'lax']},
            {'id': 'vcg-small', 'gpu_type': 'A40', 'gpu_vram_gb': 48,
             'disk': 350, 'hourly_cost': 1, 'locations': ['ewr']},
            {'id': 'vcg-tight', 'gpu_type': 'H100', 'gpu_vram_gb': 80,
             'disk': 100, 'hourly_cost': 3, 'locations': ['ewr']},
        ]
        def page(path, field):
            return plans if field == 'plans' else [{'id': 'ewr', 'city': 'New Jersey'},
                                                   {'id': 'lax', 'city': 'Los Angeles'}]
        with patch.object(vultr_control, 'pages', side_effect=page):
            self.assertEqual(vultr_control.eligible_offers(2.0), [])
            offers = vultr_control.eligible_offers(3.0)
        self.assertEqual([offer['id'] for offer in offers], ['vcg-a100@ewr', 'vcg-a100@lax'])
        self.assertEqual(offers[0]['location'], 'New Jersey')

    def test_stale_selection_never_creates_machine(self):
        with patch.dict(os.environ, {'CLOUD_GPU_STUDIO_OFFER_ID': 'gone'}), \
             patch.object(vultr_control, 'instance', return_value=None), \
             patch.object(vultr_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(vultr_control, 'eligible_offers', return_value=[{'id': 'other'}]), \
             patch.object(vultr_control, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, '刷新 Vultr 报价'):
                vultr_control.start()
            request.assert_called_once_with('account')

    def test_empty_plan_locations_uses_regional_availability(self):
        plan = {'id': 'vcg-a100', 'gpu_type': 'NVIDIA_A100', 'gpu_vram_gb': 80,
                'gpu_count': 1, 'disk': 200, 'hourly_cost': 2.5, 'locations': []}
        def page(path, field):
            return [plan] if field == 'plans' else [{'id': 'ewr', 'city': 'New Jersey'}]
        with patch.object(vultr_control, 'pages', side_effect=page), \
             patch.object(vultr_control, 'request',
                          return_value={'available_plans': ['vcg-a100']}) as request:
            offers = vultr_control.eligible_offers()
        self.assertEqual(offers[0]['id'], 'vcg-a100@ewr')
        request.assert_called_once_with('regions/ewr/availability?type=vcg')

    def test_unavailable_region_never_creates_machine(self):
        offer = {'id': 'vcg-a100@ewr', 'plan': 'vcg-a100', 'kind': 'cloud', 'region': 'ewr',
                 'gpu': 'A100', 'price': 2.0}
        with patch.dict(os.environ, {'CLOUD_GPU_STUDIO_OFFER_ID': offer['id']}), \
             patch.object(vultr_control, 'instance', return_value=None), \
             patch.object(vultr_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(vultr_control, 'eligible_offers', return_value=[offer]), \
             patch.object(vultr_control, 'request', return_value={'available_plans': []}) as request:
            with self.assertRaisesRegex(RuntimeError, '已不可用'):
                vultr_control.start()
            self.assertEqual([call.args[0] for call in request.call_args_list],
                             ['account', 'regions/ewr/availability?type=vcg'])

    def test_gh200_metal_offer_uses_bare_metal_availability(self):
        gh200 = {'id': 'vbm-gh200', 'gpu_type': 'NVIDIA_GH200', 'gpu_count': 1,
                 'gpu_vram_gb': 96, 'disk': 960, 'hourly_cost': 1.99,
                 'deploy_ondemand': True, 'locations': []}
        def page(path, field):
            if field == 'plans_metal':
                return [gh200]
            if field == 'regions':
                return [{'id': 'ewr', 'city': 'New Jersey'}]
            return []
        with patch.object(vultr_control, 'pages', side_effect=page), \
             patch.object(vultr_control, 'request',
                          return_value={'available_plans': ['vbm-gh200']}) as request:
            offers = vultr_control.eligible_offers()
        self.assertEqual(offers[0]['id'], 'vbm-gh200@ewr')
        self.assertEqual(offers[0]['kind'], 'metal')
        request.assert_called_once_with('regions/ewr/availability?type=vbm')

    def test_gh200_without_on_demand_access_is_not_offered(self):
        gh200 = {'id': 'vbm-gh200', 'gpu_type': 'NVIDIA_GH200', 'gpu_count': 1,
                 'gpu_vram_gb': 96, 'disk': 960, 'hourly_cost': 1.99,
                 'deploy_ondemand': False, 'locations': []}
        with patch.object(vultr_control, 'pages', side_effect=lambda path, field:
                          [gh200] if field == 'plans_metal' else
                          [{'id': 'ewr', 'city': 'New Jersey'}] if field == 'regions' else []), \
             patch.object(vultr_control, 'request') as request:
            self.assertEqual(vultr_control.eligible_offers(), [])
            request.assert_not_called()

    def test_metal_record_reads_only_bare_metal_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / 'deployment.json'
            location.write_text(json.dumps({'id': 'managed-id', 'kind': 'metal',
                                            'label': 'cloud-gpu-studio-owned'}))
            with patch.object(vultr_control, 'STATE', location), \
                 patch.object(vultr_control, 'request', return_value={
                     'bare_metal': {'id': 'managed-id', 'label': 'cloud-gpu-studio-owned'}}) as request:
                self.assertEqual(vultr_control.instance()['id'], 'managed-id')
                request.assert_called_once_with('bare-metals/managed-id')

    def test_gh200_requires_arm_image_before_creating_machine(self):
        systems = [{'id': 2284, 'name': 'Ubuntu 24.04 LTS x64', 'arch': 'x64'}]
        with patch.object(vultr_control, 'pages', return_value=systems):
            with self.assertRaisesRegex(RuntimeError, 'ARM64.*已停止创建'):
                vultr_control.ubuntu_os_id('NVIDIA_GH200')

    def test_gh200_uses_arm_image_when_available(self):
        systems = [{'id': 2284, 'name': 'Ubuntu 24.04 LTS x64', 'arch': 'x64'},
                   {'id': 2400, 'name': 'Ubuntu 24.04 LTS ARM64', 'arch': 'arm64'}]
        with patch.object(vultr_control, 'pages', return_value=systems):
            self.assertEqual(vultr_control.ubuntu_os_id('NVIDIA_GH200'), 2400)

    def test_stop_deletes_only_tracked_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / 'deployment.json'
            location.write_text(json.dumps({'id': 'tracked-id', 'label': 'cloud-gpu-studio-owned'}))
            with patch.object(vultr_control, 'STATE', location), \
                 patch.object(vultr_control, 'instance', side_effect=[{'id': 'tracked-id'}, None]), \
                 patch.object(vultr_control, 'request', return_value={}) as request:
                vultr_control.stop()
                request.assert_called_once_with('instances/tracked-id', method='DELETE')
                self.assertEqual(json.loads(location.read_text()), {})

    def test_stop_deletes_only_tracked_bare_metal(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / 'deployment.json'
            location.write_text(json.dumps({'id': 'tracked-id', 'kind': 'metal',
                                            'label': 'cloud-gpu-studio-owned'}))
            with patch.object(vultr_control, 'STATE', location), \
                 patch.object(vultr_control, 'instance', side_effect=[{'id': 'tracked-id'}, None]), \
                 patch.object(vultr_control, 'request', return_value={}) as request:
                vultr_control.stop()
                request.assert_called_once_with('bare-metals/tracked-id', method='DELETE')
                self.assertEqual(json.loads(location.read_text()), {})

    def test_mismatched_cloud_label_blocks_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / 'deployment.json'
            location.write_text(json.dumps({'id': 'existing-id',
                                            'label': 'cloud-gpu-studio-owned'}))
            with patch.object(vultr_control, 'STATE', location), \
                 patch.object(vultr_control, 'request',
                              return_value={'instance': {'id': 'existing-id',
                                                         'label': 'my-permanent-server'}}) as request:
                with self.assertRaises(vultr_control.OwnershipError):
                    vultr_control.stop()
                request.assert_called_once_with('instances/existing-id')

    def test_empty_catalog_explains_memory_limit(self):
        with patch.object(vultr_control, 'eligible_offers', return_value=[]), \
             patch.object(vultr_control, 'selected_price_limit', return_value=None), \
             patch.object(vultr_control, 'pages', return_value=[
                 {'gpu_type': 'NVIDIA_L40S', 'gpu_count': 1, 'gpu_vram_gb': 48},
                 {'gpu_type': 'NVIDIA_L40S', 'gpu_count': 2, 'gpu_vram_gb': 96}]), \
             patch.object(vultr_control, 'request', return_value={}):
            with self.assertRaisesRegex(RuntimeError, '最高仅 48 GB'):
                vultr_control.list_offers()


if __name__ == '__main__':
    unittest.main()
