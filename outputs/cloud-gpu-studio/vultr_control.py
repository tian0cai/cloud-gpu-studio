"""Disposable Vultr Cloud GPU instance for the local ComfyUI bridge."""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from app_config import BASE, WORK, SECRETS, manifest
from vast_control import upload_setup, launch_setup, wait_for_setup

API = 'https://api.vultr.com/v2/'
STATE = WORK / 'vultr-deployment.json'
MIN_DISK_GB = 160
MIN_VRAM_GB = 79


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(value):
    STATE.write_text(json.dumps(value, indent=2) + '\n')


def request(path, data=None, method='GET'):
    key_file = SECRETS / 'vultr_api_key'
    if not key_file.exists():
        raise RuntimeError('请先在账户设置保存 Vultr API Key。')
    key = key_file.read_text().strip()
    command = ['curl', '--silent', '--show-error', '--max-time', '45', '--config', '-',
               '--request', method, API + path.lstrip('/'), '--write-out', '\n%{http_code}']
    if data is not None:
        command += ['--data', json.dumps(data)]
    config = 'header = "Authorization: Bearer ' + key + '"\nheader = "Content-Type: application/json"\n'
    response = subprocess.run(command, input=config, text=True, capture_output=True)
    if response.returncode:
        raise RuntimeError(response.stderr.strip() or 'Vultr API connection failed.')
    body, code = response.stdout.rsplit('\n', 1)
    if not 200 <= int(code) < 300:
        # API errors can echo request information. Never show a credential-bearing body.
        raise RuntimeError('Vultr HTTP ' + code + ': ' + body[:300].replace(key, '[redacted]'))
    return json.loads(body) if body else {}


def pages(path, field):
    result = []
    cursor = None
    while True:
        suffix = ('&' if '?' in path else '?') + 'per_page=500'
        if cursor:
            suffix += '&cursor=' + quote(cursor, safe='')
        payload = request(path + suffix)
        result.extend(payload.get(field) or [])
        next_cursor = ((payload.get('meta') or {}).get('links') or {}).get('next')
        if not next_cursor or next_cursor == cursor:
            return result
        cursor = next_cursor


def instance():
    machine_id = state().get('id')
    if not machine_id:
        return None
    try:
        return request('instances/' + str(machine_id)).get('instance')
    except RuntimeError as error:
        if 'HTTP 404' in str(error):
            return None
        raise


def status():
    current = instance()
    saved = state()
    return {'pod': {'id': str(current['id']), 'costPerHr': saved.get('cost_per_hour'),
                    'desiredStatus': current.get('status'), 'gpuTypeId': saved.get('gpu_type')}
            if current else None,
            'balance': None, 'old_network_volume_still_billed': None, 'provider': 'vultr'}


def selected_price_limit():
    raw = os.environ.get('CLOUD_GPU_STUDIO_MAX_HOURLY')
    if not raw:
        return None
    value = float(raw)
    if not 0 < value < float('inf'):
        raise RuntimeError('每小时价格上限必须是高于 $0 的有限数字。')
    return value


def eligible_offers(max_hourly=None):
    plans = pages('plans?type=vcg', 'plans')
    regions = {item['id']: item for item in pages('regions', 'regions')}
    candidates = []
    for plan in plans:
        gpu_name = str(plan.get('gpu_type') or '')
        vram = float(plan.get('gpu_vram_gb') or plan.get('gpu_vram') or 0)
        disk = float(plan.get('disk') or 0)
        price = float(plan.get('hourly_cost') or 0)
        gpu_count = int(plan.get('gpu_count') or 1)
        gpu_brand = str(plan.get('gpu_brand') or '')
        if (not gpu_name or re.search(r'AMD|INSTINCT|RADEON|\bMI\d',
                                   gpu_name + ' ' + gpu_brand, re.I) or
                vram < MIN_VRAM_GB or disk < MIN_DISK_GB or
                gpu_count != 1 or price <= 0 or (max_hourly is not None and price > max_hourly)):
            continue
        candidates.append(plan)
    # Vultr sometimes returns empty plan.locations even though regional
    # availability is populated. Fall back to the authoritative region API.
    regional_plans = {}
    if candidates and not any(plan.get('locations') for plan in candidates):
        def available(region_id):
            data = request('regions/' + quote(region_id, safe='') + '/availability')
            return region_id, set(data.get('available_plans') or [])
        with ThreadPoolExecutor(max_workers=6) as pool:
            regional_plans = dict(pool.map(available, regions))
    offers = []
    for plan in candidates:
        gpu_name = str(plan.get('gpu_type') or '')
        vram = float(plan.get('gpu_vram_gb') or plan.get('gpu_vram') or 0)
        disk = float(plan.get('disk') or 0)
        price = float(plan.get('hourly_cost') or 0)
        locations = plan.get('locations') or [region_id for region_id, available in
                                              regional_plans.items() if plan['id'] in available]
        for region_id in locations:
            region = regions.get(region_id)
            if not region:
                continue
            offers.append({'id': f"{plan['id']}@{region_id}", 'plan': plan['id'],
                           'region': region_id, 'gpu': gpu_name, 'price': price,
                           'location': str(region.get('city') or region_id),
                           'vramGb': vram, 'diskGb': disk, 'reliability': None})
    return sorted(offers, key=lambda item: (item['price'], item['gpu'], item['region']))


def list_offers():
    return [{key: value for key, value in item.items() if key not in ('plan', 'region')}
            for item in eligible_offers(selected_price_limit())]


def ensure_ssh_key():
    from runpod_control import ensure_ssh_key as ensure_local_ssh_key
    ensure_local_ssh_key()
    public = (SECRETS / 'runpod_ed25519.pub').read_text().strip()
    for item in pages('ssh-keys', 'ssh_keys'):
        if item.get('ssh_key', '').strip() == public:
            return item['id']
    created = request('ssh-keys', {'name': 'cloud-gpu-studio', 'ssh_key': public}, 'POST')
    return created['ssh_key']['id']


def ubuntu_os_id():
    systems = pages('os', 'os')
    for version in ('24.04', '22.04'):
        candidates = [item for item in systems if
                      re.search(r'Ubuntu\s+' + re.escape(version) + r'\b',
                                str(item.get('name') or ''), re.I)
                      and 'x64' in str(item.get('name') or '')]
        if candidates:
            candidates.sort(key=lambda item: 0 if re.search(
                r'gpu|nvidia', str(item.get('name') or ''), re.I) else 1)
            return candidates[0]['id']
    raise RuntimeError('Vultr 没有返回支持的 Ubuntu 22.04/24.04 x64 镜像。')


def ssh_info(current):
    host = current.get('main_ip') if current else None
    if not host or host == '0.0.0.0':
        return None
    known_hosts = SECRETS / ('known_hosts_vultr_' + str(current['id']))
    options = ['-i', str(SECRETS / 'runpod_ed25519'), '-o', 'StrictHostKeyChecking=accept-new',
               '-o', 'UserKnownHostsFile=' + str(known_hosts), '-o', 'ConnectTimeout=15',
               '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3']
    return {'host': 'root@' + host, 'port': '22', 'options': options}


def ssh_command(info, *remote):
    return ['ssh', *info['options'], '-p', info['port'], info['host'], *remote]


def ssh_ready(info):
    try:
        return subprocess.run(ssh_command(info, 'true'), capture_output=True, timeout=25).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def prepare_host(info):
    # Vultr's GPU-enabled Ubuntu image supplies the NVIDIA driver. Only userland
    # tools are installed here; changing the driver could break GPU access.
    command = ('export DEBIAN_FRONTEND=noninteractive; '
               'command -v nvidia-smi >/dev/null && nvidia-smi -L && '
               'apt-get update -qq && apt-get install -y -qq '
               'python3 python3-venv python3-pip python-is-python3 git curl ca-certificates && '
               'mkdir -p /workspace/bootstrap /workspace/logs')
    subprocess.run(ssh_command(info, command), check=True, timeout=900)


def deploy_existing(info):
    saved = state()
    saved['metrics_ssh'] = info
    save_state(saved)
    print('GPU_SSH_READY', flush=True)
    prepare_host(info)
    selected_manifest = manifest()
    upload_setup(info, selected_manifest)
    total_gb = sum(item['size'] for item in json.loads(selected_manifest.read_text())['files']) / 1e9
    print(f'Installing ComfyUI and downloading {total_gb:.1f} GB of models.', flush=True)
    wait_for_setup(info, launch_setup(info))


def start():
    if instance():
        raise RuntimeError('Vultr machine already exists; connect it instead.')
    selected_manifest = manifest()
    limit = selected_price_limit()
    offers = eligible_offers(limit)
    selected_id = os.environ.get('CLOUD_GPU_STUDIO_OFFER_ID')
    offer = next((item for item in offers if item['id'] == selected_id), None) if selected_id else None
    if not offer:
        raise RuntimeError('请刷新 Vultr 报价并选择一台机器；所选方案可能已下架或涨价。')
    available = request('regions/' + quote(offer['region'], safe='') + '/availability').get('available_plans') or []
    if offer['plan'] not in available:
        raise RuntimeError('选中的 Vultr 机型在该地区已不可用，请刷新报价。')
    key_id = ensure_ssh_key()
    os_id = ubuntu_os_id()
    print(f"Creating Vultr {offer['gpu']} in {offer['region']} at ${offer['price']:.2f}/hour.", flush=True)
    created = request('instances', {'region': offer['region'], 'plan': offer['plan'],
                                    'os_id': os_id, 'label': 'cloud-gpu-studio',
                                    'hostname': 'cloud-gpu-studio', 'sshkey_id': [key_id],
                                    'backups': 'disabled'}, 'POST').get('instance') or {}
    machine_id = created.get('id')
    if not machine_id:
        raise RuntimeError('Vultr did not return an instance ID; inspect the console before retrying.')
    save_state({'id': machine_id, 'created_epoch': time.time(), 'cost_per_hour': offer['price'],
                'max_hourly': limit, 'gpu_type': offer['gpu'], 'offer_id': offer['id'],
                'model': json.loads(selected_manifest.read_text())})
    with (WORK / 'vultr-budget-guard.log').open('a') as log:
        subprocess.Popen([sys.executable, '-u', __file__, 'guard'], cwd=BASE,
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    # Keep an allocated machine if installation fails so the user can inspect
    # and explicitly delete it; the background cost guard remains active.
    for _ in range(90):
        current = instance()
        info = ssh_info(current)
        if info and ssh_ready(info):
            break
        time.sleep(10)
    else:
        raise RuntimeError('Vultr SSH startup exceeded 15 minutes; machine remains available for retry or deletion.')
    deploy_existing(info)


def resume():
    current = instance()
    if not current:
        raise RuntimeError('No tracked Vultr machine is available to resume.')
    for _ in range(90):
        current = instance()
        info = ssh_info(current)
        if info and ssh_ready(info):
            break
        time.sleep(10)
    else:
        raise RuntimeError('The existing Vultr machine did not become reachable by SSH.')
    health = subprocess.run(ssh_command(info, 'curl -fsS --max-time 3 http://127.0.0.1:8188/system_stats'),
                            capture_output=True, timeout=25)
    if health.returncode == 0:
        print('GPU_SSH_READY', flush=True)
        print('CLOUD_READY', flush=True)
    else:
        deploy_existing(info)


def stop():
    machine_id = state().get('id')
    if not machine_id:
        print('No tracked Vultr instance.', flush=True)
        return
    if instance():
        try:
            request('instances/' + str(machine_id), method='DELETE')
        except RuntimeError as error:
            if 'HTTP 404' not in str(error):
                raise
    for _ in range(30):
        if not instance():
            save_state({})
            print('Vultr instance and disposable disk deleted. Local outputs are unchanged.', flush=True)
            return
        time.sleep(2)
    raise RuntimeError('Vultr deletion has not completed; check the console.')


def guard():
    saved = state()
    if not saved.get('id'):
        return
    while True:
        try:
            if state().get('id') != saved['id'] or instance() is None:
                return
            elapsed = time.time() - saved['created_epoch']
            if elapsed * saved['cost_per_hour'] / 3600 >= 9 or elapsed >= 3 * 3600:
                request('instances/' + str(saved['id']), method='DELETE')
                print('Budget guard deleted Vultr instance.', flush=True)
                return
        except Exception as error:
            print(str(error)[:300], flush=True)
        time.sleep(30)


def connect():
    current = instance()
    info = ssh_info(current)
    if not info:
        raise RuntimeError('Vultr SSH address is not ready.')
    subprocess.run(['ssh', *info['options'], '-p', info['port'], '-N', '-L',
                    '127.0.0.1:8189:127.0.0.1:8188', '-o', 'ExitOnForwardFailure=yes',
                    info['host']], check=True)


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'status':
        print(json.dumps(status()))
    elif command == 'offers':
        print(json.dumps(list_offers()))
    else:
        {'start': start, 'resume': resume, 'stop': stop, 'connect': connect, 'guard': guard}[command]()
