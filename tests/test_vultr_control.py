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
            request.assert_not_called()

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
        request.assert_called_once_with('regions/ewr/availability')

    def test_unavailable_region_never_creates_machine(self):
        offer = {'id': 'vcg-a100@ewr', 'plan': 'vcg-a100', 'region': 'ewr',
                 'gpu': 'A100', 'price': 2.0}
        with patch.dict(os.environ, {'CLOUD_GPU_STUDIO_OFFER_ID': offer['id']}), \
             patch.object(vultr_control, 'instance', return_value=None), \
             patch.object(vultr_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(vultr_control, 'eligible_offers', return_value=[offer]), \
             patch.object(vultr_control, 'request', return_value={'available_plans': []}) as request:
            with self.assertRaisesRegex(RuntimeError, '已不可用'):
                vultr_control.start()
            request.assert_called_once_with('regions/ewr/availability')

    def test_stop_deletes_only_tracked_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / 'deployment.json'
            location.write_text(json.dumps({'id': 'tracked-id'}))
            with patch.object(vultr_control, 'STATE', location), \
                 patch.object(vultr_control, 'instance', side_effect=[{'id': 'tracked-id'}, None]), \
                 patch.object(vultr_control, 'request', return_value={}) as request:
                vultr_control.stop()
                request.assert_called_once_with('instances/tracked-id', method='DELETE')
                self.assertEqual(json.loads(location.read_text()), {})


if __name__ == '__main__':
    unittest.main()
