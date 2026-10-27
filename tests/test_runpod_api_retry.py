import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / 'outputs' / 'cloud-gpu-studio'
sys.path.insert(0, str(SCRIPTS))
import runpod_api


class RunPodApiRetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.secrets = Path(self.temporary.name)
        (self.secrets / 'runpod_api_key').write_text('test-key')
        self.addCleanup(self.temporary.cleanup)

    def test_status_read_retries_a_transient_server_error(self):
        results = [types.SimpleNamespace(returncode=0, stdout='busy\n503', stderr=''),
                   types.SimpleNamespace(returncode=0, stdout='[{"id":"pod-1"}]\n200', stderr='')]
        with patch.object(runpod_api, 'SECRETS', self.secrets), \
             patch.object(runpod_api.subprocess, 'run', side_effect=results) as run, \
             patch.object(runpod_api.time, 'sleep') as sleep:
            self.assertEqual(runpod_api.request('pods'), [{'id': 'pod-1'}])
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_mutation_is_not_repeated(self):
        failure = types.SimpleNamespace(returncode=0, stdout='busy\n503', stderr='')
        with patch.object(runpod_api, 'SECRETS', self.secrets), \
             patch.object(runpod_api.subprocess, 'run', return_value=failure) as run, \
             patch.object(runpod_api.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'RunPod HTTP 503'):
                runpod_api.request('pods/pod-1', method='DELETE')
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_graphql_query_retries_but_mutation_does_not(self):
        timeout = types.SimpleNamespace(returncode=28, stdout='', stderr='curl timeout')
        ok = types.SimpleNamespace(returncode=0, stdout='{"data":{"myself":{}}}\n200', stderr='')
        with patch.object(runpod_api, 'SECRETS', self.secrets), \
             patch.object(runpod_api.subprocess, 'run', side_effect=[timeout, ok]) as run, \
             patch.object(runpod_api.time, 'sleep'):
            self.assertEqual(runpod_api.gql('query { myself { id } }'), {'myself': {}})
        self.assertEqual(run.call_count, 2)
        with patch.object(runpod_api, 'SECRETS', self.secrets), \
             patch.object(runpod_api.subprocess, 'run', return_value=timeout) as run:
            with self.assertRaisesRegex(RuntimeError, 'curl timeout'):
                runpod_api.request('', {'query': 'mutation { podStop { id } }'}, graphql=True)
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
