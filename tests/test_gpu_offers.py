import sys
import os
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / 'outputs' / 'cloud-gpu-studio'
sys.path.insert(0, str(SCRIPTS))
import runpod_control
import vast_control


class GpuOfferTests(unittest.TestCase):
    def test_vast_quote_includes_storage_for_requested_disk(self):
        offer = {'gpu_name': 'A800 PCIE', 'num_gpus': 1, 'gpu_ram': 81920, 'compute_cap': 800,
                 'disk_space': 200, 'direct_port_count': 1, 'reliability2': 0.98,
                 'dph_total': 0.80, 'storage_cost': 0.40, 'id': 1}
        expected = 0.80 + 0.40 * (vast_control.DISK_GB - vast_control.DEFAULT_DISK_GB) / 30 / 24
        self.assertAlmostEqual(vast_control.estimated_hourly(offer), expected)
        with patch.object(vast_control, 'request', return_value={'offers': [offer]}):
            self.assertEqual(vast_control.eligible_offers(0.80), [])
            self.assertEqual([item['id'] for item in vast_control.eligible_offers(1.00)], [1])

    def test_vast_includes_a800_but_obeys_price_and_host_requirements(self):
        base = {'gpu_name': 'A800 PCIE', 'num_gpus': 1, 'gpu_ram': 81920, 'compute_cap': 800,
                'disk_space': 200, 'direct_port_count': 1, 'reliability2': 0.98,
                'dph_total': 0.78, 'id': 1}
        offers = [base, {**base, 'id': 2, 'dph_total': 2.1},
                  {**base, 'id': 3, 'direct_port_count': 0},
                  {**base, 'id': 4, 'reliability2': 0.7}]
        with patch.object(vast_control, 'request', return_value={'offers': offers}):
            self.assertEqual([item['id'] for item in vast_control.eligible_offers(1.0)], [1])
            self.assertEqual([item['id'] for item in vast_control.eligible_offers(None)], [1, 2])

    def test_vast_keeps_a_quote_for_each_gpu_model_after_first_hundred(self):
        common = {'gpu_ram': 81920, 'reliability2': 0.98, 'geolocation': 'test'}
        offers = [{**common, 'id': n, 'gpu_name': 'A100 SXM', 'dph_total': 0.5 + n / 1000}
                  for n in range(100)]
        offers.append({**common, 'id': 100, 'gpu_name': 'A800 PCIE', 'dph_total': 1.2})
        with patch.object(vast_control, 'eligible_offers', return_value=offers), \
             patch.object(vast_control, 'selected_price_limit', return_value=None):
            catalog = vast_control.list_offers()
        self.assertEqual(len(catalog), 101)
        self.assertIn('A800 PCIE', {item['gpu'] for item in catalog})

    def test_runpod_catalog_is_datacenter_specific_and_price_capped(self):
        def fake_gql(query):
            if 'dataCenters' in query:
                return {'dataCenters': [{'id': 'DC-1'}, {'id': 'DC-2'}]}
            if 'q0:' in query:
                return {'q0': [{'lowestPrice': {'uninterruptablePrice': 1.79, 'stockStatus': 'High'}}],
                        'q1': [{'lowestPrice': {'uninterruptablePrice': 2.2, 'stockStatus': 'High'}}]}
            return {'gpuTypes': [{'id': 'NVIDIA A100 80GB PCIe', 'memoryInGb': 80,
                                  'lowestPrice': {'uninterruptablePrice': 1.79}}]}
        with patch.object(runpod_control, 'gql', side_effect=fake_gql):
            catalog = runpod_control.offer_catalog(2.0)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]['id'], 'NVIDIA A100 80GB PCIe|DC-1')
        self.assertEqual(catalog[0]['price'], 1.79)
        with patch.object(runpod_control, 'gql', side_effect=fake_gql):
            self.assertEqual(len(runpod_control.offer_catalog(None)), 2)

    def test_stale_vast_selection_never_creates_another_offer(self):
        with patch.dict(os.environ, {'CLOUD_GPU_STUDIO_OFFER_ID': 'missing'}), \
             patch.object(vast_control, 'instance', return_value=None), \
             patch.object(vast_control, 'available_funds', return_value=20), \
             patch.object(vast_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(vast_control, 'ensure_ssh_key'), \
             patch.object(vast_control, 'eligible_offers', return_value=[{'id': 1}]), \
             patch.object(vast_control, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, '刷新报价'):
                vast_control.start()
            request.assert_not_called()

    def test_vast_retries_disappeared_offer_only_with_same_gpu_under_price_cap(self):
        chosen = {'id': 10, 'gpu_name': 'B200', 'dph_total': 6.0}
        alternate = {'id': 11, 'gpu_name': 'B200', 'dph_total': 6.1}
        other_gpu = {'id': 12, 'gpu_name': 'B300', 'dph_total': 5.0}
        with patch.object(vast_control, 'request', side_effect=[
                RuntimeError('Vast.ai HTTP 400: no_such_ask'), {'new_contract': 42}]) as request, \
             patch.object(vast_control, 'eligible_offers', return_value=[other_gpu, alternate]) as eligible:
            created, used = vast_control.create_with_same_gpu_retry(chosen, 6.2)
        self.assertEqual(created['new_contract'], 42)
        self.assertEqual(used['id'], 11)
        eligible.assert_called_once_with(6.2)
        self.assertEqual([call.args[0] for call in request.call_args_list], ['asks/10/', 'asks/11/'])

    def test_vast_does_not_retry_ambiguous_create_error(self):
        chosen = {'id': 10, 'gpu_name': 'B200', 'dph_total': 6.0}
        with patch.object(vast_control, 'request', side_effect=RuntimeError('curl timeout')) as request, \
             patch.object(vast_control, 'eligible_offers') as eligible:
            with self.assertRaisesRegex(RuntimeError, 'curl timeout'):
                vast_control.create_with_same_gpu_retry(chosen, 6.2)
        request.assert_called_once()
        eligible.assert_not_called()

    def test_vast_disappeared_offer_without_same_gpu_stops_cleanly(self):
        chosen = {'id': 10, 'gpu_name': 'B300', 'dph_total': 7.0}
        with patch.object(vast_control, 'request', side_effect=RuntimeError('no_such_ask')) as request, \
             patch.object(vast_control, 'eligible_offers', return_value=[
                 {'id': 12, 'gpu_name': 'B200', 'dph_total': 6.0}]) as eligible:
            with self.assertRaisesRegex(RuntimeError, '请刷新报价后重试'):
                vast_control.create_with_same_gpu_retry(chosen, 7.0)
        request.assert_called_once()
        eligible.assert_called_once_with(7.0)


if __name__ == '__main__':
    unittest.main()
