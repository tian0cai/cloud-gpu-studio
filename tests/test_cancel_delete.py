"""Deletion stays safe when two cleanup paths race on the same machine."""
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'outputs' / 'cloud-gpu-studio'
sys.path.insert(0, str(SCRIPTS))
import runpod_control
import vast_control


class ConcurrentDeleteTests(unittest.TestCase):
    def test_runpod_already_deleted_after_lookup(self):
        with patch.object(runpod_control, 'state', return_value={'pod': {'id': 'pod-1'}}), \
             patch.object(runpod_control, 'current_pod', side_effect=[{'id': 'pod-1'}, None]), \
             patch.object(runpod_control, 'request', side_effect=RuntimeError('RunPod HTTP 404')):
            runpod_control.stop()

    def test_vast_already_deleted_after_lookup(self):
        with patch.object(vast_control, 'state', return_value={'id': 123}), \
             patch.object(vast_control, 'instance', side_effect=[{'id': 123}, None]), \
             patch.object(vast_control, 'request', side_effect=RuntimeError('Vast.ai HTTP 404')), \
             patch.object(vast_control, 'save_state') as save:
            vast_control.stop()
            save.assert_called_once_with({})

    def test_runpod_non_404_delete_error_is_reported(self):
        with patch.object(runpod_control, 'state', return_value={'pod': {'id': 'pod-1'}}), \
             patch.object(runpod_control, 'current_pod', return_value={'id': 'pod-1'}), \
             patch.object(runpod_control, 'request', side_effect=RuntimeError('RunPod HTTP 500')):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 500'):
                runpod_control.stop()

    def test_resume_ready_runpod_machine_does_not_reinstall(self):
        ready = SimpleNamespace(returncode=0)
        with patch.object(runpod_control, 'current_pod', return_value={'id': 'pod-1'}), \
             patch.object(runpod_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(runpod_control, 'ssh_info', return_value={'host': 'test', 'port': '22', 'options': []}), \
             patch.object(runpod_control, 'state', return_value={'pod': {'id': 'pod-1'}}), \
             patch.object(runpod_control, 'save_state'), \
             patch.object(runpod_control.subprocess, 'run', return_value=ready) as run:
            runpod_control.resume()
            self.assertEqual(run.call_count, 2)

    def test_resume_runpod_retries_a_timed_out_handshake(self):
        ready = SimpleNamespace(returncode=0)
        timeout = subprocess.TimeoutExpired('ssh', 25)
        with patch.object(runpod_control, 'current_pod', return_value={'id': 'pod-1'}), \
             patch.object(runpod_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(runpod_control, 'ssh_info', return_value={'host': 'test', 'port': '22', 'options': []}), \
             patch.object(runpod_control, 'state', return_value={'pod': {'id': 'pod-1'}}), \
             patch.object(runpod_control, 'save_state'), \
             patch.object(runpod_control.time, 'sleep'), \
             patch.object(runpod_control, 'stop') as stop, \
             patch.object(runpod_control.subprocess, 'run', side_effect=[timeout, ready, ready]) as run:
            runpod_control.resume()
            self.assertEqual(run.call_count, 3)
            stop.assert_not_called()

    def test_resume_ready_vast_machine_does_not_reinstall(self):
        ready = SimpleNamespace(returncode=0)
        with patch.object(vast_control, 'instance', return_value={'id': 123}), \
             patch.object(vast_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(vast_control, 'ssh_info', return_value={'host': 'test', 'port': '22', 'options': []}), \
             patch.object(vast_control, 'state', return_value={'id': 123}), \
             patch.object(vast_control, 'save_state'), \
             patch.object(vast_control.subprocess, 'run', return_value=ready) as run:
            vast_control.resume()
            self.assertEqual(run.call_count, 2)

    def test_resume_vast_retries_a_timed_out_handshake(self):
        ready = SimpleNamespace(returncode=0)
        timeout = subprocess.TimeoutExpired('ssh', 25)
        with patch.object(vast_control, 'instance', return_value={'id': 123}), \
             patch.object(vast_control, 'manifest', return_value=Path('/tmp/unused')), \
             patch.object(vast_control, 'ssh_info', return_value={'host': 'test', 'port': '22', 'options': []}), \
             patch.object(vast_control, 'state', return_value={'id': 123}), \
             patch.object(vast_control, 'save_state'), \
             patch.object(vast_control.time, 'sleep'), \
             patch.object(vast_control.subprocess, 'run', side_effect=[timeout, ready, ready]) as run:
            vast_control.resume()
            self.assertEqual(run.call_count, 3)

    def test_resume_incomplete_runpod_machine_retries_bootstrap_without_deleting(self):
        ready = SimpleNamespace(returncode=0)
        not_ready = SimpleNamespace(returncode=7)
        with patch.object(runpod_control, 'current_pod', return_value={'id': 'pod-1'}), \
             patch.object(runpod_control, 'manifest', return_value=Path('/tmp/models.lock.json')), \
             patch.object(runpod_control, 'ssh_info', return_value={'host': 'test', 'port': '22', 'options': []}), \
             patch.object(runpod_control, 'state', return_value={'pod': {'id': 'pod-1'}}), \
             patch.object(runpod_control, 'save_state'), \
             patch.object(runpod_control, 'stop') as stop, \
             patch.object(runpod_control.subprocess, 'run', side_effect=[ready, not_ready, ready, ready, ready, ready]) as run:
            runpod_control.resume()
            self.assertEqual(run.call_count, 6)
            stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
