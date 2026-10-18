import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / 'outputs' / 'cloud-gpu-studio'
sys.path.insert(0, str(SCRIPTS))
import host_metrics
import vast_control


class HostMetricsTests(unittest.TestCase):
    def test_probe_is_valid_remote_python(self):
        compile(host_metrics.REMOTE_PROBE, '<remote telemetry>', 'exec')

    def test_no_instance_does_not_open_ssh(self):
        with patch.object(vast_control, 'state', return_value={}), \
             patch.object(host_metrics.subprocess, 'run') as run:
            self.assertEqual(host_metrics.collect('vast'), {'online': False})
            run.assert_not_called()

    def test_metrics_are_read_over_selected_provider_ssh(self):
        sample = {'cpuPercent': 12.5, 'ramUsedGb': 10, 'ramTotalGb': 96,
                  'gpuPercent': 70, 'vramUsedGb': 42, 'vramTotalGb': 80}
        with patch.object(vast_control, 'state', return_value={'id': 42}), \
             patch.object(vast_control, 'instance', return_value={'id': 42}), \
             patch.object(vast_control, 'ssh_info', return_value={'host': 'test'}), \
             patch.object(vast_control, 'ssh_command', return_value=['ssh', 'test']), \
             patch.object(host_metrics.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(sample))):
            self.assertEqual(host_metrics.collect('vast'), {'online': True, **sample})

    def test_cached_ssh_target_avoids_provider_api_per_sample(self):
        sample = {'cpuPercent': 4, 'gpuPercent': 0, 'ramUsedGb': 2,
                  'ramTotalGb': 96, 'vramUsedGb': 1, 'vramTotalGb': 80}
        with patch.object(vast_control, 'state', return_value={'id': 42,
                 'metrics_ssh': {'host': 'root@test', 'port': '22', 'options': []}}), \
             patch.object(vast_control, 'instance') as instance, \
             patch.object(host_metrics.subprocess, 'run', return_value=SimpleNamespace(
                 returncode=0, stdout=json.dumps(sample))) as run:
            self.assertTrue(host_metrics.collect('vast')['online'])
            instance.assert_not_called()
            self.assertIn('ControlMaster=auto', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
