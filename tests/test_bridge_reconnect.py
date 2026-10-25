import ast
import io
import types
import unittest
import uuid
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'outputs/cloud-gpu-studio/comfyui_cloud_bridge/__init__.py'


class BridgeReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text())
        selected = [node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name in {'CloudConnectionError', 'RemoteClient'}]
        class Timeout(Exception):
            pass
        class ConnectionError(Exception):
            pass
        requests = types.SimpleNamespace(exceptions=types.SimpleNamespace(
            Timeout=Timeout, ConnectionError=ConnectionError))
        class Pixels:
            def cpu(self): return self
            def numpy(self): return self
            def __mul__(self, factor): return self
            def astype(self, dtype): return self
        class Image:
            @staticmethod
            def fromarray(array):
                return types.SimpleNamespace(save=lambda buffer, format: buffer.write(b'PNG'))
        namespace = {'requests': requests, 'ENDPOINT': 'http://127.0.0.1:8189',
                     'time': types.SimpleNamespace(sleep=lambda seconds: None),
                     'io': io, 'uuid': uuid, 'Image': Image,
                     'np': types.SimpleNamespace(clip=lambda array, low, high: array,
                                                 uint8=object())}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), namespace)
        cls.RemoteClient = namespace['RemoteClient']
        cls.CloudConnectionError = namespace['CloudConnectionError']
        cls.Timeout = Timeout
        cls.Pixels = Pixels

    def test_get_recovers_after_transient_tunnel_timeout(self):
        response = types.SimpleNamespace(ok=True)
        calls = []
        def request(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise self.Timeout()
            return response
        client = object.__new__(self.RemoteClient)
        client.session = types.SimpleNamespace(request=request)
        self.assertIs(client.request('GET', '/history/job'), response)
        self.assertEqual(len(calls), 2)

    def test_prompt_post_is_never_automatically_repeated(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(args)
            raise self.Timeout()
        client = object.__new__(self.RemoteClient)
        client.session = types.SimpleNamespace(request=request)
        with self.assertRaises(self.CloudConnectionError):
            client.request('POST', '/prompt', json={})
        self.assertEqual(len(calls), 1)

    def test_image_upload_retries_after_connection_loss(self):
        client = object.__new__(self.RemoteClient)
        calls = []
        def request(method, path, **kwargs):
            calls.append((method, path))
            if len(calls) == 1:
                raise self.CloudConnectionError('temporary disconnect')
            return types.SimpleNamespace(json=lambda: {'name': 'uploaded.png'})
        client.request = request
        self.assertEqual(client.upload([self.Pixels()]), 'uploaded.png')
        self.assertEqual(calls, [('POST', '/upload/image')] * 2)


if __name__ == '__main__':
    unittest.main()
