import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'outputs/cloud-gpu-studio/comfyui_cloud_bridge/__init__.py'


class H3ReferenceGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text())
        selected = [item for item in tree.body if isinstance(item, ast.FunctionDef)
                    and item.name in {'node', 'h3_graph', 'h3_reference_graph'}]
        namespace = {'model_files': lambda kind: {
            'unet': 'fl2va.safetensors', 'clip': 'encoder.safetensors',
            'video_vae': 'video-vae.safetensors', 'audio_vae': 'audio-vae.safetensors',
            'lora': 'fl2va-lora.safetensors'}}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), namespace)
        cls.reference_graph = staticmethod(namespace['h3_reference_graph'])

    def test_two_images_use_native_autogrow_reference_slots(self):
        graph = self.reference_graph('Use <Picture 1> and <Picture 2>', 1, 20,
                                     768, 768, 124, ['one.png', 'two.png'])
        self.assertEqual(graph['1']['inputs']['unet_name'],
                         'minimax_h3_ref2va_pruned_int8_convrot.safetensors')
        self.assertEqual(graph['5']['class_type'], 'MiniMaxH3ReferenceToVideo')
        self.assertEqual(graph['5']['inputs']['ref_images.ref_image_0'], ['15', 0])
        self.assertEqual(graph['5']['inputs']['ref_images.ref_image_1'], ['16', 0])
        self.assertEqual(graph['16']['inputs']['image'], 'two.png')
        self.assertNotIn('first_frame', graph['5']['inputs'])
        self.assertNotIn('17', graph)

    def test_reference_count_is_bounded(self):
        with self.assertRaisesRegex(ValueError, 'at least one'):
            self.reference_graph('prompt', 1, 20, 768, 768, 124, [])
        with self.assertRaisesRegex(ValueError, 'at most nine'):
            self.reference_graph('prompt', 1, 20, 768, 768, 124, ['x'] * 10)


if __name__ == '__main__':
    unittest.main()
