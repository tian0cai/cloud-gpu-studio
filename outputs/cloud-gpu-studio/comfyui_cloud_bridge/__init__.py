# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 tian0cai

import asyncio
import io
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

import aiohttp
import numpy as np
import requests
import torch
from PIL import Image

import folder_paths
import comfy.model_management
import comfy.utils
from comfy_api.latest import InputImpl

ENDPOINT = 'http://127.0.0.1:8189'
OVERRIDES = Path(os.environ.get('CLOUD_GPU_STUDIO_WORK_DIR',
                                Path.home() / '.cloud-gpu-studio')) / 'model-overrides.json'


def model_files(kind):
    defaults = {
        'qwen': {'unet': 'qwen_image_2.1_int8_convrot.safetensors',
                 'clip': 'qwen3vl_8b_int8_convrot.safetensors',
                 'vae': 'qwen_image_2.1_vae_bf16.safetensors'},
        'h3': {'unet': 'minimax_h3_fl2va_int8_convrot.safetensors',
               'clip': 'qwen3vl_32b_minimax_h3_int8_convrot.safetensors',
               'video_vae': 'minimax_h3_video_vae_fp16.safetensors',
               'audio_vae': 'minimax_h3_audio_vae_fp32.safetensors', 'lora': None},
    }
    settings_path = OVERRIDES.parent / 'app-settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    selected = settings.get('image_model' if kind == 'qwen' else 'video_model')
    if selected is None:
        selected = 'local-qwen' if kind == 'qwen' and settings.get('model') == 'local' else (
            'local-h3' if kind == 'h3' and settings.get('model') == 'local' else kind)
    if selected == 'none' or (kind == 'qwen' and selected == 'checkpoint'):
        raise RuntimeError(f'{kind} model is not selected in Cloud GPU Studio.')
    if selected == 'local-' + kind and OVERRIDES.exists():
        return {**defaults[kind], **json.loads(OVERRIDES.read_text()).get(kind, {})}
    return defaults[kind]


def node(class_type, **inputs):
    return {'class_type': class_type, 'inputs': inputs}


def qwen_graph(prompt, negative_prompt, seed, steps, width, height, uploaded=None):
    files = model_files('qwen')
    graph = {
        '1': node('UNETLoader', unet_name=files['unet'], weight_dtype='default'),
        '2': node('CLIPLoader', clip_name=files['clip'], type='qwen_image', device='default'),
        '3': node('VAELoader', vae_name=files['vae']),
        '4': node('TextEncodeQwenImage21', clip=['2', 0], prompt=prompt, negative_prompt=negative_prompt, resolution=width),
        '5': node('EmptyLatentImage', width=width, height=height, batch_size=1),
        '6': node('KSampler', model=['1', 0], positive=['4', 0], negative=['4', 1], latent_image=['5', 0], seed=seed, steps=steps, cfg=3.0, sampler_name='euler', scheduler='simple', denoise=1.0),
        '7': node('VAEDecode', samples=['6', 0], vae=['3', 0]),
        '8': node('SaveImage', images=['7', 0], filename_prefix='cloud-gpu-studio/qwen'),
    }
    if uploaded:
        graph['9'] = node('LoadImage', image=uploaded)
        graph['4']['inputs'].update({'images.image_1': ['9', 0], 'vae': ['3', 0]})
        graph['6']['inputs']['latent_image'] = ['4', 2]
    return graph


def custom_checkpoint_graph(prompt, negative_prompt, seed, steps, width, height):
    settings_path = OVERRIDES.parent / 'app-settings.json'
    settings = json.loads(settings_path.read_text())
    if settings.get('image_model', 'checkpoint' if settings.get('model') == 'custom' else None) != 'checkpoint' or not settings.get('custom_model'):
        raise RuntimeError('请先在桌面端选择并部署 Hugging Face checkpoint。')
    filename = Path(settings['custom_model']['destination']).name
    return {
        '1': node('CheckpointLoaderSimple', ckpt_name=filename),
        '2': node('CLIPTextEncode', text=prompt, clip=['1', 1]),
        '3': node('CLIPTextEncode', text=negative_prompt, clip=['1', 1]),
        '4': node('EmptyLatentImage', width=width, height=height, batch_size=1),
        '5': node('KSampler', model=['1', 0], positive=['2', 0], negative=['3', 0],
                  latent_image=['4', 0], seed=seed, steps=steps, cfg=7.0,
                  sampler_name='euler', scheduler='normal', denoise=1.0),
        '6': node('VAEDecode', samples=['5', 0], vae=['1', 2]),
        '7': node('SaveImage', images=['6', 0], filename_prefix='cloud/custom'),
    }


def h3_graph(prompt, seed, steps, width, height, frames, uploaded=None, lora_strength=0.0):
    files = model_files('h3')
    graph = {
        '1': node('UNETLoader', unet_name=files['unet'], weight_dtype='default'),
        '2': node('CLIPLoader', clip_name=files['clip'], type='minimax', device='default'),
        '3': node('VAELoader', vae_name=files['video_vae']),
        '4': node('VAELoader', vae_name=files['audio_vae']),
        '5': node('MiniMaxH3ImageToVideo', clip=['2', 0], vae=['3', 0], prompt=prompt, width=width, height=height, length=frames),
        '6': node('RandomNoise', noise_seed=seed),
        '7': node('BasicGuider', model=['1', 0], conditioning=['5', 0]),
        '8': node('KSamplerSelect', sampler_name='res_multistep'),
        '9': node('BasicScheduler', model=['1', 0], scheduler='simple', steps=steps, denoise=1.0),
        '10': node('SamplerCustomAdvanced', noise=['6', 0], guider=['7', 0], sampler=['8', 0], sigmas=['9', 0], latent_image=['5', 1]),
        '11': node('VAEDecode', samples=['10', 0], vae=['3', 0]),
        '12': node('VAEDecodeAudio', samples=['10', 0], vae=['4', 0]),
        '13': node('CreateVideo', images=['11', 0], audio=['12', 0], fps=24.0),
        '14': node('SaveVideo', video=['13', 0], filename_prefix='cloud-gpu-studio/h3', format='mp4', **{'format.codec': 'h264'}),
    }
    if uploaded:
        graph['15'] = node('LoadImage', image=uploaded)
        graph['5']['inputs']['first_frame'] = ['15', 0]
    if lora_strength > 0:
        if not files.get('lora'):
            raise ValueError('Choose a video LoRA in local model overrides before increasing its strength.')
        graph['16'] = node('LoraLoaderModelOnly', model=['1', 0],
                           lora_name=files['lora'], strength_model=lora_strength)
        graph['7']['inputs']['model'] = ['16', 0]
        graph['9']['inputs']['model'] = ['16', 0]
    settings_path = OVERRIDES.parent / 'app-settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    if settings.get('h3_attention') == 'sol-attn':
        model = graph['7']['inputs']['model']
        graph['17'] = node('BlockSparseAttention', model=model,
                           selection='sol-attn', **{'selection.tau': 1.3},
                           start_percent=0.2, end_percent=1.0, dense_blocks='',
                           min_tokens=12288, extra_tokens=256,
                           sink_conditioning='exact_kv_and_rows', verbose=True)
        graph['7']['inputs']['model'] = ['17', 0]
        graph['9']['inputs']['model'] = ['17', 0]
    return graph


def h3_reference_graph(prompt, seed, steps, width, height, frames, uploaded):
    if not uploaded:
        raise ValueError('Ref2VA requires at least one reference image.')
    if len(uploaded) > 9:
        raise ValueError('Ref2VA accepts at most nine reference images.')
    graph = h3_graph(prompt, seed, steps, width, height, frames)
    graph['1']['inputs']['unet_name'] = 'minimax_h3_ref2va_pruned_int8_convrot.safetensors'
    conditioning = graph['5']
    conditioning['class_type'] = 'MiniMaxH3ReferenceToVideo'
    conditioning['inputs']['audio_vae'] = ['4', 0]
    conditioning['inputs']['ref_image_size'] = 'match'
    # Keep reference image IDs away from the optional LoRA and attention nodes.
    for index, filename in enumerate(uploaded):
        key = str(20 + index)
        graph[key] = node('LoadImage', image=filename)
        conditioning['inputs'][f'ref_images.ref_image_{index}'] = [key, 0]
    graph['14']['inputs']['filename_prefix'] = 'cloud-gpu-studio/h3-ref2va'
    return graph


def video_mode():
    path = OVERRIDES.parent / 'app-settings.json'
    return json.loads(path.read_text()).get('video_mode', 'ref2va') if path.exists() else 'ref2va'


class RemoteClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False

    def request(self, method, path, **kwargs):
        try:
            response = self.session.request(method, ENDPOINT + path, timeout=(10, 120), **kwargs)
        except requests.exceptions.ConnectionError as error:
            raise RuntimeError('云端 ComfyUI 尚未连接。请等待 Cloud GPU Studio 主窗口显示“云端已连接”，再执行工作流；若机器已启动，请在主窗口重新连接。') from error
        if not response.ok:
            raise RuntimeError(f'Cloud GPU HTTP {response.status_code}: {response.text[:2000]}')
        return response

    def upload(self, image):
        if image is None:
            return None
        buffer = io.BytesIO()
        pixels = np.clip(image[0].cpu().numpy() * 255, 0, 255).astype(np.uint8)
        Image.fromarray(pixels).save(buffer, format='PNG')
        filename = f'local_{uuid.uuid4().hex}.png'
        data = self.request('POST', '/upload/image', files={'image': (filename, buffer.getvalue(), 'image/png')}, data={'type': 'input'}).json()
        return '/'.join(filter(None, [data.get('subfolder'), data['name']]))

    def run(self, graph, extension, steps, node_id=None):
        client_id = uuid.uuid4().hex
        with ProgressRelay(client_id, steps, node_id) as progress:
            result = self.request('POST', '/prompt', json={'prompt': graph, 'client_id': client_id}).json()
            prompt_id = result['prompt_id']
            started = time.monotonic()
            while time.monotonic() - started < 7200:
                progress.drain(prompt_id)
                try:
                    comfy.model_management.throw_exception_if_processing_interrupted()
                except comfy.model_management.InterruptProcessingException:
                    self.request('POST', '/queue', json={'delete': [prompt_id]})
                    self.request('POST', '/interrupt', json={'prompt_id': prompt_id})
                    raise
                history = self.request('GET', '/history/' + prompt_id).json().get(prompt_id)
                if history:
                    status = history.get('status', {})
                    if status.get('status_str') == 'error':
                        raise RuntimeError(f'Cloud task {prompt_id} failed: {status.get("messages")}')
                    if status.get('completed'):
                        progress.finish()
                        for output in history.get('outputs', {}).values():
                            for key in ('images', 'videos', 'gifs'):
                                for item in output.get(key, []):
                                    if Path(item['filename']).suffix.lower() != extension:
                                        continue
                                    filename = f'{prompt_id}{extension}'
                                    dest = Path(folder_paths.get_output_directory()) / 'cloud-gpu-studio' / filename
                                    dest.parent.mkdir(parents=True, exist_ok=True)
                                    response = self.request('GET', '/view', params={k: item[k] for k in ('filename', 'subfolder', 'type') if k in item}, stream=True)
                                    partial = dest.with_suffix(extension + '.part')
                                    with partial.open('wb') as f:
                                        for chunk in response.iter_content(1024 * 1024):
                                            f.write(chunk)
                                    partial.replace(dest)
                                    return dest, {'filename': filename, 'subfolder': 'cloud-gpu-studio', 'type': 'output'}
                        raise RuntimeError(f'Task {prompt_id} completed without a {extension} output')
                time.sleep(2)
            self.request('POST', '/queue', json={'delete': [prompt_id]})
            self.request('POST', '/interrupt', json={'prompt_id': prompt_id})
            raise TimeoutError(f'Task {prompt_id} exceeded 2 hours; cancellation requested.')


class ProgressRelay:
    """Forward cloud WebSocket sampler progress to the local ComfyUI node."""
    def __init__(self, client_id, steps, node_id):
        self.client_id = client_id
        self.bar = comfy.utils.ProgressBar(steps, node_id=node_id)
        self.events = queue.SimpleQueue()
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.listen, daemon=True)

    async def listen_async(self):
        try:
            async with aiohttp.ClientSession(trust_env=False) as session:
                async with session.ws_connect(ENDPOINT + '/ws', params={'clientId': self.client_id}, heartbeat=20) as ws:
                    self.ready.set()
                    while not self.stop.is_set():
                        try:
                            msg = await ws.receive(timeout=2)
                        except asyncio.TimeoutError:
                            continue
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            if event.get('type') == 'progress':
                                data = event.get('data', {})
                                self.events.put((data.get('prompt_id'), data.get('value'), data.get('max')))
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
        except (aiohttp.ClientError, OSError, ValueError):
            pass  # History polling still delivers the result if progress events are unavailable.
        finally:
            self.ready.set()

    def listen(self):
        asyncio.run(self.listen_async())

    def __enter__(self):
        self.bar.update_absolute(0)
        self.thread.start()
        self.ready.wait(timeout=5)
        return self

    def drain(self, prompt_id):
        while not self.events.empty():
            event_prompt, value, total = self.events.get()
            if event_prompt == prompt_id and isinstance(value, int) and isinstance(total, int) and total > 0:
                self.bar.update_absolute(value, total)

    def finish(self):
        self.bar.update_absolute(self.bar.total)

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=3)


def common_inputs():
    return {
        'prompt': ('STRING', {'multiline': True, 'default': 'A small wooden boat on a calm mountain lake at sunrise, cinematic natural light.'}),
        'seed': ('INT', {'default': 42, 'min': 0, 'max': 0xffffffffffffffff}),
        'steps': ('INT', {'default': 20, 'min': 1, 'max': 100}),
        'width': ('INT', {'default': 768, 'min': 256, 'max': 2048, 'step': 32}),
        'height': ('INT', {'default': 768, 'min': 256, 'max': 2048, 'step': 32}),
    }


class CloudQwenImage:
    @classmethod
    def INPUT_TYPES(cls):
        required = common_inputs()
        required['steps'][1]['default'] = 25
        required['width'][1]['default'] = 1024
        required['height'][1]['default'] = 1024
        required['negative_prompt'] = ('STRING', {'multiline': True, 'default': ''})
        return {'required': required, 'optional': {'reference_image': ('IMAGE',)},
                'hidden': {'unique_id': 'UNIQUE_ID'}}

    RETURN_TYPES = ('IMAGE', 'STRING')
    RETURN_NAMES = ('image', 'local_path')
    FUNCTION = 'generate'
    CATEGORY = 'Cloud GPU Studio'
    OUTPUT_NODE = True

    def generate(self, prompt, seed, steps, width, height, negative_prompt='', reference_image=None, unique_id=None):
        client = RemoteClient()
        graph = qwen_graph(prompt, negative_prompt, seed, steps, width, height, client.upload(reference_image))
        dest, saved = client.run(graph, '.png', steps, unique_id)
        with Image.open(dest) as image:
            tensor = torch.from_numpy(np.asarray(image.convert('RGB')).astype(np.float32) / 255.0)[None]
        return {'ui': {'images': [saved]}, 'result': (tensor, str(dest))}


class CloudCheckpointImage:
    @classmethod
    def INPUT_TYPES(cls):
        required = common_inputs()
        required['negative_prompt'] = ('STRING', {'multiline': True, 'default': ''})
        return {'required': required, 'hidden': {'unique_id': 'UNIQUE_ID'}}

    RETURN_TYPES = ('IMAGE', 'STRING')
    RETURN_NAMES = ('image', 'local_path')
    FUNCTION = 'generate'
    CATEGORY = 'Cloud GPU Studio'
    OUTPUT_NODE = True

    def generate(self, prompt, seed, steps, width, height, negative_prompt='', unique_id=None):
        graph = custom_checkpoint_graph(prompt, negative_prompt, seed, steps, width, height)
        dest, saved = RemoteClient().run(graph, '.png', steps, unique_id)
        with Image.open(dest) as image:
            tensor = torch.from_numpy(np.asarray(image.convert('RGB')).astype(np.float32) / 255.0)[None]
        return {'ui': {'images': [saved]}, 'result': (tensor, str(dest))}


class CloudH3Video:
    @classmethod
    def INPUT_TYPES(cls):
        required = common_inputs()
        required['frames'] = ('INT', {'default': 124, 'min': 5, 'max': 362, 'step': 17})
        required['lora_strength'] = ('FLOAT', {'default': 0.0, 'min': 0.0, 'max': 1.0, 'step': 0.05})
        optional = {'first_frame': ('IMAGE',)}
        optional.update({f'reference_{index}': ('IMAGE',) for index in range(2, 10)})
        return {'required': required, 'optional': optional,
                'hidden': {'unique_id': 'UNIQUE_ID'}}

    RETURN_TYPES = ('VIDEO', 'STRING')
    RETURN_NAMES = ('video', 'local_path')
    FUNCTION = 'generate'
    CATEGORY = 'Cloud GPU Studio'
    OUTPUT_NODE = True

    def generate(self, prompt, seed, steps, width, height, frames, lora_strength=0.0,
                 first_frame=None, unique_id=None, **references):
        client = RemoteClient()
        images = [first_frame] + [references.get(f'reference_{index}') for index in range(2, 10)]
        if video_mode() == 'ref2va':
            if lora_strength > 0:
                raise ValueError('当前 LoRA 仅用于 FL2VA；Ref2VA 模式请将 LoRA 强度设为 0。')
            uploaded = [client.upload(image) for image in images if image is not None]
            graph = h3_reference_graph(prompt, seed, steps, width, height, frames, uploaded)
        else:
            if any(image is not None for image in images[1:]):
                raise ValueError('多参考图需要先在桌面端下载 Ref2VA 主模型并切换模式。')
            graph = h3_graph(prompt, seed, steps, width, height, frames, client.upload(first_frame),
                             lora_strength)
        dest, saved = client.run(graph, '.mp4', steps, unique_id)
        return {'ui': {'images': [saved], 'animated': (True,)}, 'result': (InputImpl.VideoFromFile(str(dest)), str(dest))}


class CloudH3FirstFrameVideo(CloudH3Video):
    @classmethod
    def INPUT_TYPES(cls):
        required = common_inputs()
        required['frames'] = ('INT', {'default': 124, 'min': 5, 'max': 362, 'step': 17})
        required['lora_strength'] = ('FLOAT', {'default': 0.0, 'min': 0.0, 'max': 1.0, 'step': 0.05})
        required['first_frame'] = ('IMAGE',)
        return {'required': required, 'hidden': {'unique_id': 'UNIQUE_ID'}}

    def generate(self, prompt, seed, steps, width, height, frames, first_frame,
                 lora_strength=0.0, unique_id=None):
        if video_mode() != 'fl2va':
            raise ValueError('单图首帧工作流需要先在桌面端切换到 FL2VA 模式。')
        return super().generate(prompt, seed, steps, width, height, frames,
                                lora_strength, first_frame, unique_id)


class CloudH3ReferenceVideo(CloudH3Video):
    @classmethod
    def INPUT_TYPES(cls):
        required = common_inputs()
        required['frames'] = ('INT', {'default': 124, 'min': 5, 'max': 362, 'step': 17})
        required['reference_1'] = ('IMAGE',)
        optional = {f'reference_{index}': ('IMAGE',) for index in range(2, 10)}
        return {'required': required, 'optional': optional,
                'hidden': {'unique_id': 'UNIQUE_ID'}}

    def generate(self, prompt, seed, steps, width, height, frames, reference_1,
                 unique_id=None, **references):
        if video_mode() != 'ref2va':
            raise ValueError('多图参考工作流需要先在桌面端切换到 Ref2VA 模式。')
        return super().generate(prompt, seed, steps, width, height, frames,
                                0.0, reference_1, unique_id, **references)


NODE_CLASS_MAPPINGS = {'CloudQwenImage': CloudQwenImage, 'CloudH3Video': CloudH3Video,
                       'CloudH3FirstFrameVideo': CloudH3FirstFrameVideo,
                       'CloudH3ReferenceVideo': CloudH3ReferenceVideo,
                       'CloudCheckpointImage': CloudCheckpointImage}
NODE_DISPLAY_NAME_MAPPINGS = {'CloudQwenImage': 'Cloud · Qwen Image 2.1',
                              'CloudH3Video': 'Cloud · MiniMax H3 INT8',
                              'CloudH3FirstFrameVideo': 'Cloud · H3 单图首帧（FL2VA）',
                              'CloudH3ReferenceVideo': 'Cloud · H3 多图参考（Ref2VA）',
                              'CloudCheckpointImage': 'Cloud · Hugging Face Checkpoint'}
