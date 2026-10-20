import ast
import json
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'outputs/cloud-gpu-studio/comfyui_cloud_bridge/__init__.py'


class H3ReferenceGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.settings = Path(cls.temp.name) / 'app-settings.json'
        tree = ast.parse(SOURCE.read_text())
        selected = [item for item in tree.body if isinstance(item, ast.FunctionDef)
                    and item.name in {'node', 'h3_graph', 'h3_reference_graph'}]
        namespace = {'json': json, 'OVERRIDES': Path(cls.temp.name) / 'model-overrides.json',
                     'model_files': lambda kind: {
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
        self.assertEqual(graph['5']['inputs']['ref_images.ref_image_0'], ['20', 0])
        self.assertEqual(graph['5']['inputs']['ref_images.ref_image_1'], ['21', 0])
        self.assertEqual(graph['21']['inputs']['image'], 'two.png')
        self.assertNotIn('first_frame', graph['5']['inputs'])
        self.assertNotIn('17', graph)

    def test_reference_count_is_bounded(self):
        with self.assertRaisesRegex(ValueError, 'at least one'):
            self.reference_graph('prompt', 1, 20, 768, 768, 124, [])
        with self.assertRaisesRegex(ValueError, 'at most nine'):
            self.reference_graph('prompt', 1, 20, 768, 768, 124, ['x'] * 10)

    def test_sol_attn_patches_both_sampler_model_inputs(self):
        self.settings.write_text('{"h3_attention":"sol-attn"}')
        self.addCleanup(self.settings.unlink)
        graph = self.reference_graph('prompt', 1, 20, 768, 768, 124, ['one.png'])
        self.assertEqual(graph['17']['class_type'], 'BlockSparseAttention')
        self.assertEqual(graph['17']['inputs']['selection'], 'sol-attn')
        self.assertEqual(graph['17']['inputs']['selection.tau'], 1.3)
        self.assertEqual(graph['17']['inputs']['sink_conditioning'], 'exact_kv_and_rows')
        self.assertEqual(graph['7']['inputs']['model'], ['17', 0])
        self.assertEqual(graph['9']['inputs']['model'], ['17', 0])
        self.assertEqual(graph['20']['class_type'], 'LoadImage')

    def test_nine_references_do_not_replace_attention_node(self):
        self.settings.write_text('{"h3_attention":"sol-attn"}')
        self.addCleanup(self.settings.unlink)
        graph = self.reference_graph('prompt', 1, 20, 768, 768, 124,
                                     [f'{index}.png' for index in range(9)])
        self.assertEqual(graph['17']['class_type'], 'BlockSparseAttention')
        self.assertEqual({graph[str(index)]['class_type'] for index in range(20, 29)}, {'LoadImage'})


if __name__ == '__main__':
    unittest.main()
