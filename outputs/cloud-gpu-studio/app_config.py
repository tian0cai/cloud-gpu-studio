"""Local, user-editable provider and ComfyUI model settings."""
import json
import os
import re
import struct
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(os.environ.get('CLOUD_GPU_STUDIO_HOME', Path(__file__).resolve().parents[2]))
WORK = Path(os.environ.get('CLOUD_GPU_STUDIO_WORK_DIR', BASE / 'work'))
SETTINGS = WORK / 'app-settings.json'
SECRETS = WORK / 'secrets'
DEFAULT = {'provider': 'runpod', 'image_model': 'qwen', 'video_model': 'h3',
           'video_mode': 'ref2va', 'h3_attention': 'standard', 'custom_model': None}
KEY_FILES = {'runpod': 'runpod_api_key', 'vast': 'vast_api_key', 'vultr': 'vultr_api_key'}
DEPLOYMENT_FILES = {'runpod': 'deployment.json', 'vast': 'vast-deployment.json',
                    'vultr': 'vultr-deployment.json'}
MODEL_OVERRIDES = WORK / 'model-overrides.json'
REF2VA_READY = WORK / 'ref2va-ready.json'
FL2VA_READY = WORK / 'fl2va-ready.json'


def model_ready(marker_path):
    try:
        marker = json.loads(marker_path.read_text())
        provider = json.loads((WORK / 'active-provider.json').read_text())['provider']
        state_file = WORK / DEPLOYMENT_FILES[provider]
        state = json.loads(state_file.read_text())
        machine_id = (state.get('pod') or {}).get('id') if provider == 'runpod' else state.get('id')
        return bool(machine_id and marker == {'provider': provider, 'id': str(machine_id)})
    except (OSError, ValueError, KeyError, TypeError):
        return False


def ref2va_ready():
    return model_ready(REF2VA_READY)


def fl2va_ready():
    return model_ready(FL2VA_READY)


def read():
    saved = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    if 'image_model' not in saved or 'video_model' not in saved:
        legacy = saved.get('model', 'both')
        saved['image_model'] = {'both': 'qwen', 'h3': 'none', 'qwen': 'qwen',
                                'custom': 'checkpoint', 'local': 'local-qwen'}.get(legacy, 'qwen')
        saved['video_model'] = {'both': 'h3', 'h3': 'h3', 'qwen': 'none',
                                'custom': 'none', 'local': 'local-h3'}.get(legacy, 'h3')
    return {**DEFAULT, **saved}


def public_settings():
    value = read()
    return {**{key: value.get(key) for key in DEFAULT},
            'keys': {provider: (SECRETS / filename).exists()
                              for provider, filename in KEY_FILES.items()},
            'local_models_available': local_model_manifest() is not None,
            'local_pack': local_pack_summary(), 'ref2va_ready': ref2va_ready(),
            'fl2va_ready': fl2va_ready()}


def local_model_manifest():
    if not MODEL_OVERRIDES.exists():
        return None
    try:
        overrides = json.loads(MODEL_OVERRIDES.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    name = overrides.get('model_manifest')
    if not isinstance(name, str) or Path(name).name != name:
        return None
    path = WORK / name
    return path if path.is_file() else None


MODEL_COMPONENTS = {
    'h3': {'unet': 'diffusion_models', 'clip': 'text_encoders',
           'video_vae': 'vae', 'audio_vae': 'vae', 'lora': 'loras'},
    'qwen': {'unet': 'diffusion_models', 'clip': 'text_encoders', 'vae': 'vae'},
}


def validate_local_pack():
    source = local_model_manifest()
    if source is None:
        raise ValueError('Local model pack is missing. Add a manifest and model-overrides.json in work/.')
    overrides = json.loads(MODEL_OVERRIDES.read_text())
    files = json.loads(source.read_text()).get('files')
    if not isinstance(files, list):
        raise ValueError('Local model manifest must contain a files list.')
    for kind, components in MODEL_COMPONENTS.items():
        mapping = overrides.get(kind)
        if not isinstance(mapping, dict):
            raise ValueError(f'Local {kind} component mapping is missing.')
        for role, directory in components.items():
            filename = mapping.get(role)
            if role == 'lora' and not filename:
                continue
            if not isinstance(filename, str) or not filename or Path(filename).name != filename:
                raise ValueError(f'Invalid {kind} {role} component filename.')
            matches = [file for file in files if file.get('preset') == kind
                       and file.get('destination') == f'{directory}/{filename}']
            if len(matches) != 1:
                raise ValueError(f'Local {kind} {role} is not uniquely present in its manifest.')
    for file in files:
        if file.get('preset') not in MODEL_COMPONENTS:
            raise ValueError('Local model file must have an h3 or qwen preset.')
        validate_file(file)
    return files, overrides


def local_pack_summary():
    try:
        files, overrides = validate_local_pack()
        urls = {}
        for kind, components in MODEL_COMPONENTS.items():
            urls[kind] = {}
            for role, directory in components.items():
                name = overrides[kind].get(role)
                item = next((file for file in files if file.get('preset') == kind
                             and file.get('destination') == f'{directory}/{name}'), None)
                if item:
                    urls[kind][role] = ('https://huggingface.co/' + item['repo'] + '/blob/'
                                       + item['revision'] + '/' + item['filename'])
        return {'ready': True, 'image': overrides['qwen'], 'video': overrides['h3'],
                'urls': urls, 'size_gb': round(sum(file['size'] for file in files) / 1e9, 1)}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return {'ready': False, 'error': str(error)}


def validate_file(item):
    destination = item.get('destination')
    if (not isinstance(destination, str) or destination.startswith('/')
            or '..' in destination.split('/') or Path(destination).name == ''):
        raise ValueError('Unsafe destination in model manifest.')
    if (not isinstance(item.get('repo'), str) or not re.fullmatch(r'[A-Za-z0-9._-]+/[A-Za-z0-9._-]+', item['repo'])
            or not isinstance(item.get('revision'), str) or not re.fullmatch(r'[0-9a-f]{40}', item['revision'])
            or not isinstance(item.get('filename'), str) or item['filename'].startswith('/')
            or '..' in item['filename'].split('/')
            or not isinstance(item.get('size'), int) or item['size'] <= 0
            or not isinstance(item.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
        raise ValueError('Incomplete or invalid pinned model file.')


def write(value):
    if value['provider'] not in KEY_FILES:
        raise ValueError('Unsupported cloud provider.')
    if value.get('image_model') not in ('qwen', 'local-qwen', 'checkpoint', 'none'):
        raise ValueError('Unsupported image model.')
    if value.get('video_model') not in ('h3', 'local-h3', 'none'):
        raise ValueError('Unsupported video model.')
    if value.get('video_mode', DEFAULT['video_mode']) not in ('fl2va', 'ref2va'):
        raise ValueError('Unsupported H3 video mode.')
    if value.get('h3_attention', DEFAULT['h3_attention']) not in ('standard', 'sol-attn'):
        raise ValueError('Unsupported H3 attention mode.')
    if value.get('video_mode') == 'ref2va' and (WORK / 'active-provider.json').exists() and not ref2va_ready():
        raise ValueError('Download and verify the Ref2VA model on this machine before switching.')
    if value.get('video_mode') == 'fl2va' and (WORK / 'active-provider.json').exists() and not fl2va_ready():
        raise ValueError('Download and verify the FL2VA model on this machine before switching.')
    if value['image_model'] == value['video_model'] == 'none':
        raise ValueError('Select at least one model.')
    if value['image_model'] == 'checkpoint' and not value.get('custom_model'):
        raise ValueError('Select a Hugging Face checkpoint first.')
    if value['image_model'] == 'checkpoint':
        validate_file(value['custom_model'])
        if not value['custom_model']['destination'].startswith('checkpoints/'):
            raise ValueError('Custom image checkpoint must be stored in checkpoints/.')
    if value['image_model'] == 'local-qwen' or value['video_model'] == 'local-h3':
        validate_local_pack()
    active = WORK / 'active-provider.json'
    if active.exists() and any(value.get(field) != read().get(field)
                               for field in ('provider', 'image_model', 'video_model', 'custom_model')):
        raise ValueError('Delete the current cloud machine before changing provider or model.')
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o700)
    clean = {key: value.get(key, DEFAULT[key]) for key in DEFAULT}
    temporary = SETTINGS.with_suffix('.tmp')
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(SETTINGS)


def save_key(provider, key):
    if provider not in KEY_FILES:
        raise ValueError('Unsupported cloud provider.')
    if not key or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ValueError('API Key must be a nonempty printable token without spaces.')
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o700)
    SECRETS.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS, 0o700)
    destination = SECRETS / KEY_FILES[provider]
    temporary = destination.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(key + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def parse_hf_url(url):
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme != 'https' or parsed.netloc != 'huggingface.co':
        raise ValueError('Please enter a huggingface.co HTTPS model or file URL.')
    parts = [urllib.parse.unquote(p) for p in parsed.path.strip('/').split('/')]
    if len(parts) < 2 or not all(re.fullmatch(r'[A-Za-z0-9._-]+', p) for p in parts[:2]):
        raise ValueError('The Hugging Face URL must contain owner/repository.')
    repo = '/'.join(parts[:2])
    filename = None
    revision = 'main'
    if len(parts) > 2:
        if parts[2] not in ('blob', 'resolve') or len(parts) < 5:
            raise ValueError('Use a repository URL or a model file URL.')
        revision = parts[3]
        filename = '/'.join(parts[4:])
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', revision) or '..' in revision:
        raise ValueError('Unsupported revision name.')
    if filename and (filename.startswith('/') or '..' in filename.split('/')):
        raise ValueError('Unsafe model path.')
    return repo, revision, filename


def resolve_hf_file(url, directory):
    repo, revision, requested = parse_hf_url(url)
    endpoint = ('https://huggingface.co/api/models/' + urllib.parse.quote(repo, safe='/')
                + '/revision/' + urllib.parse.quote(revision, safe='') + '?blobs=true')
    with urllib.request.urlopen(endpoint, timeout=30) as response:
        metadata = json.load(response)
    commit = metadata.get('sha')
    if not commit or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Could not resolve a fixed Hugging Face commit.')
    candidates = []
    for item in metadata.get('siblings', []):
        name = item.get('rfilename', '')
        lfs = item.get('lfs') or {}
        if (name.endswith('.safetensors') and lfs.get('sha256') and lfs.get('size')
                and (not requested or name == requested)):
            candidates.append({'repo': repo, 'revision': commit, 'filename': name,
                               'destination': directory + '/' + Path(name).name,
                               'size': int(lfs['size']), 'sha256': lfs['sha256']})
    if requested and not candidates:
        raise ValueError('This file is not a public LFS .safetensors checkpoint with SHA-256 metadata.')
    if len(candidates) != 1:
        raise ValueError('Select a specific .safetensors file URL; this repository has zero or multiple candidates.')
    return candidates[0]


def inspect_hf(url):
    candidate = resolve_hf_file(url, 'checkpoints')
    repo = candidate['repo']
    commit = candidate['revision']
    file_url = ('https://huggingface.co/' + repo + '/resolve/' + commit + '/'
                + urllib.parse.quote(candidate['filename'], safe='/'))
    request = urllib.request.Request(file_url, headers={'Range': 'bytes=0-16777223'})
    with urllib.request.urlopen(request, timeout=30) as response:
        length_bytes = response.read(8)
        if len(length_bytes) != 8:
            raise ValueError('Could not inspect the safetensors header.')
        header_size = struct.unpack('<Q', length_bytes)[0]
        if not 0 < header_size <= 16 * 1024 * 1024:
            raise ValueError('Safetensors header is too large for automatic compatibility checking.')
        header = json.loads(response.read(header_size))
    keys = tuple(header)
    if not (any(name.startswith('model.diffusion_model.') for name in keys)
            and any(name.startswith('first_stage_model.') for name in keys)
            and (any(name.startswith('cond_stage_model.') for name in keys)
                 or any(name.startswith('conditioner.embedders.') for name in keys))):
        raise ValueError('This file is not a self-contained SD/SDXL checkpoint supported by the generic ComfyUI loader.')
    return candidate


def save_pack(urls):
    if (WORK / 'active-provider.json').exists():
        raise ValueError('Delete the current cloud machine before changing its model pack.')
    files = []
    overrides = {'model_manifest': 'custom-models.lock.json'}
    for kind, components in MODEL_COMPONENTS.items():
        provided = urls.get(kind)
        if not isinstance(provided, dict):
            raise ValueError(f'Missing {kind} component URLs.')
        overrides[kind] = {}
        for role, directory in components.items():
            url = provided.get(role, '').strip() if isinstance(provided.get(role, ''), str) else ''
            if role == 'lora' and not url:
                continue
            if not url:
                raise ValueError(f'Missing {kind} {role} URL.')
            item = resolve_hf_file(url, directory)
            item['preset'] = kind
            files.append(item)
            overrides[kind][role] = Path(item['destination']).name
    if len({file['destination'] for file in files}) != len(files):
        raise ValueError('Two components would use the same model filename.')
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o700)
    manifest_target = WORK / 'custom-models.lock.json'
    manifest_temp = manifest_target.with_suffix('.tmp')
    overrides_temp = MODEL_OVERRIDES.with_suffix('.tmp')
    manifest_temp.write_text(json.dumps({'files': files}, indent=2) + '\n')
    overrides_temp.write_text(json.dumps(overrides, indent=2) + '\n')
    os.chmod(manifest_temp, 0o600)
    os.chmod(overrides_temp, 0o600)
    manifest_temp.replace(manifest_target)
    overrides_temp.replace(MODEL_OVERRIDES)
    validate_local_pack()
    return public_settings()


def manifest():
    settings = read()
    official = json.loads((Path(__file__).parent / 'models.lock.json').read_text())['files']
    local = validate_local_pack()[0] if (settings['image_model'] == 'local-qwen'
                                         or settings['video_model'] == 'local-h3') else []
    files = []
    if settings['video_model'] != 'none' and settings['video_mode'] == 'ref2va':
        files.extend(json.loads((Path(__file__).parent / 'ref2va.lock.json').read_text())['files'])
    for choice, preset in ((settings['video_model'], 'h3'), (settings['image_model'], 'qwen')):
        if choice == 'none':
            continue
        if choice == 'checkpoint':
            files.append(settings['custom_model'])
        else:
            selected = [item for item in (local if choice.startswith('local-') else official)
                        if item.get('preset') == preset]
            if preset == 'h3' and settings['video_mode'] == 'ref2va':
                selected = [item for item in selected if not (
                    item['destination'].startswith('diffusion_models/')
                    or item['destination'].startswith('loras/'))]
            files.extend(selected)
    if not files:
        raise ValueError('The selected model preset has no files.')
    destinations = set()
    for item in files:
        validate_file(item)
        if item['destination'] in destinations:
            raise ValueError('Two model files have the same destination.')
        destinations.add(item['destination'])
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o700)
    target = WORK / 'selected-models.lock.json'
    target.write_text(json.dumps({'files': files}, indent=2) + '\n')
    os.chmod(target, 0o600)
    return target


if __name__ == '__main__':
    import sys
    try:
        command = sys.argv[1]
        if command == 'settings':
            print(json.dumps(public_settings()))
        elif command == 'save':
            write(json.load(sys.stdin))
            print(json.dumps(public_settings()))
        elif command == 'key':
            value = json.load(sys.stdin)
            save_key(value['provider'], value['key'])
            print(json.dumps(public_settings()))
        elif command == 'inspect':
            print(json.dumps(inspect_hf(json.load(sys.stdin)['url'])))
        elif command == 'save-pack':
            print(json.dumps(save_pack(json.load(sys.stdin)['urls'])))
        else:
            raise ValueError('Unknown configuration command.')
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
