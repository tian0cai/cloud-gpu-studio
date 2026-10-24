"""Disposable Vultr GPU instance or GH200 server for the ComfyUI bridge."""
import json
import os
import re
import secrets
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


class OwnershipError(RuntimeError):
    """A local record must never authorize actions on an unrelated VM."""


def resource_for(saved):
    kind = saved.get('kind', 'cloud')
    if kind == 'cloud':
        return 'instances', 'instance'
    if kind == 'metal':
        return 'bare-metals', 'bare_metal'
    raise OwnershipError('未知 Vultr 资源类型；为保护其他机器，已拒绝操作。')


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(value):
    STATE.write_text(json.dumps(value, indent=2) + '\n')


def request(path, data=None, method='GET'):
    key_file = SECRETS / 'vultr_api_key'
    if not key_file.exists():
        raise RuntimeError('请先在账户设置保存 Vultr API Key。')
    key = key_file.read_text().strip()
    command = ['curl', '-4', '--silent', '--show-error', '--max-time', '45', '--config', '-',
               '--request', method, API + path.lstrip('/'), '--write-out', '\n%{http_code}']
    if data is not None:
        command += ['--data', json.dumps(data)]
    config = 'header = "Authorization: Bearer ' + key + '"\nheader = "Content-Type: application/json"\n'
    response = subprocess.run(command, input=config, text=True, capture_output=True)
    if response.returncode:
        raise RuntimeError(response.stderr.strip() or 'Vultr API connection failed.')
    body, code = response.stdout.rsplit('\n', 1)
    if not 200 <= int(code) < 300:
        if code == '401' and 'Unauthorized IP address' in body:
            address = (json.loads(body).get('error') or '').split(': ', 1)[-1]
            raise RuntimeError('Vultr API 拒绝当前公网 IPv4 ' + address +
                               '。请在 Vultr 控制台的 API Access Control 中将该地址加入允许列表。')
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
    saved = state()
    machine_id = saved.get('id')
    if not machine_id:
        return None
    expected_label = saved.get('label')
    if not expected_label or not expected_label.startswith('cloud-gpu-studio-'):
        raise OwnershipError('Vultr 本地记录缺少应用专属标识；为保护账户中的其他机器，已拒绝操作。')
    resource, field = resource_for(saved)
    try:
        current = request(resource + '/' + str(machine_id)).get(field)
    except RuntimeError as error:
        if 'HTTP 404' in str(error):
            return None
        raise
    if current and (str(current.get('id')) != str(machine_id) or
                    current.get('label') != expected_label):
        raise OwnershipError('Vultr 云端实例标识与本地记录不一致；已拒绝连接或删除。')
    return current


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
    plans = [{**item, '_kind': 'cloud'} for item in pages('plans?type=vcg', 'plans')]
    plans += [{**item, '_kind': 'metal'} for item in pages('plans-metal', 'plans_metal')]
    regions = {item['id']: item for item in pages('regions', 'regions')}
    candidates = []
    for plan in plans:
        gpu_name = str(plan.get('gpu_type') or '')
        vram = float(plan.get('gpu_vram_gb') or plan.get('gpu_vram') or 0)
        disk = float(plan.get('disk') or 0)
        price = float(plan.get('hourly_cost') or 0)
        gpu_count = int(plan.get('gpu_count') or 1)
        gpu_brand = str(plan.get('gpu_brand') or '')
        if (not gpu_name or plan.get('deploy_ondemand') is False or
                re.search(r'AMD|INSTINCT|RADEON|\bMI\d',
                                   gpu_name + ' ' + gpu_brand, re.I) or
                vram < MIN_VRAM_GB or disk < MIN_DISK_GB or
                gpu_count != 1 or price <= 0 or (max_hourly is not None and price > max_hourly)):
            continue
        candidates.append(plan)
    # Vultr sometimes returns empty plan.locations even though regional
    # availability is populated. Fall back to the authoritative region API.
    regional_plans = {'cloud': {}, 'metal': {}}
    for kind, api_type in (('cloud', 'vcg'), ('metal', 'vbm')):
        subset = [plan for plan in candidates if plan['_kind'] == kind]
        if not subset or all(plan.get('locations') for plan in subset):
            continue
        def available(region_id):
            data = request('regions/' + quote(region_id, safe='') +
                           '/availability?type=' + api_type)
            return region_id, set(data.get('available_plans') or [])
        with ThreadPoolExecutor(max_workers=6) as pool:
            regional_plans[kind] = dict(pool.map(available, regions))
    offers = []
    for plan in candidates:
        gpu_name = str(plan.get('gpu_type') or '')
        vram = float(plan.get('gpu_vram_gb') or plan.get('gpu_vram') or 0)
        disk = float(plan.get('disk') or 0)
        price = float(plan.get('hourly_cost') or 0)
        kind = plan['_kind']
        locations = plan.get('locations') or [region_id for region_id, available in
                                              regional_plans[kind].items() if plan['id'] in available]
        for region_id in locations:
            region = regions.get(region_id)
            if not region:
                continue
            offers.append({'id': f"{plan['id']}@{region_id}", 'plan': plan['id'], 'kind': kind,
                           'region': region_id, 'gpu': gpu_name, 'price': price,
                           'location': str(region.get('city') or region_id),
                           'vramGb': vram, 'diskGb': disk, 'reliability': None})
    return sorted(offers, key=lambda item: (item['price'], item['gpu'], item['region']))


def list_offers():
    request('account')  # Plan catalogs are public; validate the configured key first.
    limit = selected_price_limit()
    offers = eligible_offers(limit)
    if not offers:
        metal = pages('plans-metal', 'plans_metal')
        gh200 = next((item for item in metal if item.get('gpu_type') == 'NVIDIA_GH200'
                      and int(item.get('gpu_count') or 1) == 1), None)
        if gh200 and gh200.get('deploy_ondemand') is False:
            raise RuntimeError('Vultr 的 Bare Metal 目录列有单卡 GH200（96 GB），但这条方案标记为不可按需部署；Cloud GPU 目录当前也没有返回可用的同型号方案。请在控制台确认 GH200 的地区和部署资格；应用不会改选其他机器。')
        plans = pages('plans?type=vcg', 'plans')
        single = [item for item in plans if int(item.get('gpu_count') or 1) == 1 and
                  not re.search(r'AMD|INSTINCT|RADEON|\bMI\d',
                                str(item.get('gpu_type') or ''), re.I)]
        max_vram = max((float(item.get('gpu_vram_gb') or 0) for item in single), default=0)
        if max_vram < MIN_VRAM_GB:
            raise RuntimeError(f'Vultr API Key 有效，但当前账户可见的单卡 Cloud GPU 最高仅 {max_vram:g} GB 显存；当前模型方案要求至少约 80 GB。多卡方案的显存不能直接相加供单个 ComfyUI 模型使用。')
        if limit is not None:
            raise RuntimeError('Vultr 当前没有价格上限内、且地区可部署的兼容单卡；可清空价格上限后重试。')
        raise RuntimeError('Vultr 当前没有地区可部署的兼容单卡；请稍后查询或联系 Vultr 确认 GPU 配额。')
    return [{key: value for key, value in item.items() if key not in ('plan', 'region', 'kind')}
            for item in offers]


def ensure_ssh_key():
    from runpod_control import ensure_ssh_key as ensure_local_ssh_key
    ensure_local_ssh_key()
    public = (SECRETS / 'runpod_ed25519.pub').read_text().strip()
    for item in pages('ssh-keys', 'ssh_keys'):
        if item.get('ssh_key', '').strip() == public:
            return item['id']
    created = request('ssh-keys', {'name': 'cloud-gpu-studio', 'ssh_key': public}, 'POST')
    return created['ssh_key']['id']


def ubuntu_os_id(gpu_name=''):
    arm = 'GH200' in gpu_name.upper()
    systems = pages('os', 'os')
    for version in ('24.04', '22.04'):
        candidates = []
        for item in systems:
            name = str(item.get('name') or '')
            arch = str(item.get('arch') or name)
            if not re.search(r'Ubuntu\s+' + re.escape(version) + r'\b', name, re.I):
                continue
            if arm and re.search(r'arm64|aarch64', name + ' ' + arch, re.I):
                candidates.append(item)
            elif not arm and (arch.lower() in ('x64', 'x86_64') or
                              re.search(r'\bx64\b', name, re.I)):
                candidates.append(item)
        if candidates:
            candidates.sort(key=lambda item: 0 if re.search(
                r'gpu|nvidia', str(item.get('name') or ''), re.I) else 1)
            return candidates[0]['id']
    arch = 'ARM64' if arm else 'x64'
    raise RuntimeError(f'Vultr 未返回适用于 {gpu_name or "此机型"} 的 Ubuntu 22.04/24.04 {arch} 镜像；已停止创建，避免产生无法启动的计费机器。')


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
    request('account')
    if instance():
        raise RuntimeError('Vultr machine already exists; connect it instead.')
    selected_manifest = manifest()
    limit = selected_price_limit()
    offers = eligible_offers(limit)
    selected_id = os.environ.get('CLOUD_GPU_STUDIO_OFFER_ID')
    offer = next((item for item in offers if item['id'] == selected_id), None) if selected_id else None
    if not offer:
        raise RuntimeError('请刷新 Vultr 报价并选择一台机器；所选方案可能已下架或涨价。')
    api_type = 'vbm' if offer['kind'] == 'metal' else 'vcg'
    available = request('regions/' + quote(offer['region'], safe='') +
                        '/availability?type=' + api_type).get('available_plans') or []
    if offer['plan'] not in available:
        raise RuntimeError('选中的 Vultr 机型在该地区已不可用，请刷新报价。')
    os_id = ubuntu_os_id(offer['gpu'])
    key_id = ensure_ssh_key()
    label = 'cloud-gpu-studio-' + secrets.token_hex(6)
    print(f"Creating Vultr {offer['gpu']} in {offer['region']} at ${offer['price']:.2f}/hour.", flush=True)
    payload = {'region': offer['region'], 'plan': offer['plan'], 'os_id': os_id,
               'label': label, 'hostname': 'cloud-gpu-studio'}
    if offer['kind'] == 'metal':
        payload['ssh_key_ids'] = [key_id]
        resource, field = 'bare-metals', 'bare_metal'
    else:
        payload['sshkey_id'] = [key_id]
        payload['backups'] = 'disabled'
        resource, field = 'instances', 'instance'
    created = request(resource, payload, 'POST').get(field) or {}
    machine_id = created.get('id')
    if not machine_id:
        raise RuntimeError('Vultr did not return an instance ID; inspect the console before retrying.')
    save_state({'id': machine_id, 'kind': offer['kind'], 'label': label,
                'created_epoch': time.time(),
                'cost_per_hour': offer['price'],
                'max_hourly': limit, 'gpu_type': offer['gpu'], 'offer_id': offer['id'],
                'model': json.loads(selected_manifest.read_text())})
    # Keep an allocated machine if installation fails so the user can inspect
    # and explicitly delete it.
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
    saved = state()
    machine_id = saved.get('id')
    if not machine_id:
        print('No tracked Vultr instance.', flush=True)
        return
    resource, _ = resource_for(saved)
    if instance():
        try:
            request(resource + '/' + str(machine_id), method='DELETE')
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


def connect():
    current = instance()
    info = ssh_info(current)
    if not info:
        raise RuntimeError('Vultr SSH address is not ready.')
    subprocess.run(['ssh', *info['options'], '-p', info['port'], '-N', '-L',
                    '127.0.0.1:8189:127.0.0.1:8188', '-o', 'ExitOnForwardFailure=yes',
                    info['host']], check=True)


if __name__ == '__main__':
    try:
        command = sys.argv[1]
        if command == 'status':
            print(json.dumps(status()))
        elif command == 'offers':
            print(json.dumps(list_offers()))
        else:
            {'start': start, 'resume': resume, 'stop': stop, 'connect': connect}[command]()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
