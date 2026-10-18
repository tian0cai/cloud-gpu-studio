"""Disposable Vast.ai on-demand GPU deployment for the local ComfyUI bridge."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from app_config import BASE, WORK, SECRETS, manifest

STATE = WORK / 'vast-deployment.json'
DEPLOYABLE = Path(__file__).resolve().parent
API = 'https://console.vast.ai/api/v0/'
IMAGE = 'pytorch/pytorch:2.8.0-cuda12.8-cudnn9-devel'
DISK_GB = 200


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(value):
    STATE.write_text(json.dumps(value, indent=2) + '\n')


def request(path, data=None, method='GET'):
    key_file = SECRETS / 'vast_api_key'
    if not key_file.exists():
        raise RuntimeError('请先在桌面端保存 Vast.ai API Key。')
    key = key_file.read_text().strip()
    url = API + path.strip('/') + '/'
    command = ['curl', '--silent', '--show-error', '--max-time', '45', '--config', '-',
               '--request', method, url, '--write-out', '\n%{http_code}']
    if data is not None:
        command += ['--data', json.dumps(data)]
    config = 'header = "Authorization: Bearer ' + key + '"\nheader = "Content-Type: application/json"\n'
    response = subprocess.run(command, input=config, text=True, capture_output=True)
    if response.returncode:
        raise RuntimeError(response.stderr.strip())
    body, code = response.stdout.rsplit('\n', 1)
    if not 200 <= int(code) < 300:
        raise RuntimeError('Vast.ai HTTP ' + code + ': ' + body[:500])
    result = json.loads(body) if body else None
    if isinstance(result, dict) and result.get('success') is False:
        raise RuntimeError('Vast.ai: ' + str(result.get('msg') or result.get('error')))
    return result


def instance():
    instance_id = state().get('id')
    if not instance_id:
        return None
    try:
        result = request('instances/' + str(instance_id) + '/')
    except RuntimeError as error:
        if 'HTTP 404' in str(error):
            return None
        raise
    return result.get('instances', result) if isinstance(result, dict) else None


def available_funds():
    account = request('users/current')
    return float(account.get('balance') or 0) + float(account.get('credit') or 0)


def status():
    current = instance()
    balance = available_funds() if (SECRETS / 'vast_api_key').exists() else None
    return {'pod': {'id': str(current['id']), 'costPerHr': current.get('dph_total'),
                    'desiredStatus': current.get('actual_status'), 'gpuTypeId': current.get('gpu_name')}
            if current else None,
            'balance': balance, 'old_network_volume_still_billed': None,
            'provider': 'vast'}


def ensure_ssh_key():
    from runpod_control import ensure_ssh_key as ensure_local_ssh_key
    ensure_local_ssh_key()
    public = (SECRETS / 'runpod_ed25519.pub').read_text().strip()
    keys = request('ssh')
    if not any(k.get('public_key', '').strip() == public and not k.get('deleted_at') for k in keys):
        request('ssh', {'ssh_key': public}, method='POST')
        print('Registered SSH public key with Vast.ai.', flush=True)


def eligible_offers(max_hourly=None):
    query = {'limit': 1000, 'type': 'on-demand', 'verified': {'eq': True},
             'rentable': {'eq': True}, 'rented': {'eq': False},
             'num_gpus': {'eq': 1}, 'gpu_ram': {'gte': 79000},
             'disk_space': {'gte': DISK_GB}}
    offers = request('bundles', query, method='POST').get('offers', [])
    if isinstance(offers, dict):
        offers = [offers]
    filtered = []
    for offer in offers:
        price = float(offer.get('dph_total') or 0)
        if (float(offer.get('compute_cap') or 0) >= 800 and offer.get('num_gpus') == 1
                and offer.get('gpu_ram', 0) >= 79000
                and offer.get('disk_space', 0) >= DISK_GB
                and offer.get('direct_port_count', 0) >= 1
                and float(offer.get('reliability2') or offer.get('reliability') or 0) >= 0.95
                and price > 0 and (max_hourly is None or price <= max_hourly)):
            filtered.append(offer)
    return sorted(filtered, key=lambda item: (float(item['dph_total']),
                                              -float(item.get('reliability2') or 0)))


def selected_price_limit():
    raw = os.environ.get('CLOUD_GPU_STUDIO_MAX_HOURLY')
    if not raw:
        return None
    value = float(raw)
    if not 0 < value < float('inf'):
        raise RuntimeError('每小时价格上限必须是高于 $0 的有限数字。')
    return value


def list_offers():
    eligible = eligible_offers(selected_price_limit())
    visible = eligible[:100]
    visible_ids = {item['id'] for item in visible}
    visible_models = {item['gpu_name'] for item in visible}
    for item in eligible[100:]:
        if item['gpu_name'] not in visible_models and item['id'] not in visible_ids:
            visible.append(item)
            visible_models.add(item['gpu_name'])
    visible.sort(key=lambda item: float(item['dph_total']))
    return [{'id': str(item['id']), 'gpu': item['gpu_name'],
             'price': float(item['dph_total']), 'location': str(item.get('geolocation') or item.get('hostname') or 'Vast.ai'),
             'vramGb': round(float(item['gpu_ram']) / 1000, 1),
             'reliability': round(float(item.get('reliability2') or item.get('reliability') or 0) * 100, 1)}
            for item in visible]


def ssh_info(current):
    host = current.get('ssh_host')
    port = current.get('ssh_port')
    if not host or not port:
        return None
    known_hosts = SECRETS / ('known_hosts_vast_' + str(current['id']))
    options = ['-i', str(SECRETS / 'runpod_ed25519'), '-o', 'StrictHostKeyChecking=accept-new',
               '-o', 'UserKnownHostsFile=' + str(known_hosts), '-o', 'ConnectTimeout=15',
               '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3']
    return {'host': 'root@' + host, 'port': str(port), 'options': options}


def ssh_command(info, *remote):
    return ['ssh', *info['options'], '-p', info['port'], info['host'], *remote]


def start():
    if instance():
        raise RuntimeError('Vast.ai instance already exists; connect it instead.')
    balance = available_funds()
    if balance < 10:
        raise RuntimeError('Vast.ai balance is below $10. Add funds before creating a paid instance.')
    selected_manifest = manifest()
    ensure_ssh_key()
    max_hourly = selected_price_limit()
    offers = eligible_offers(max_hourly)
    if not offers:
        raise RuntimeError(f'当前没有符合要求的 80 GB 单卡机器（{DISK_GB} GB 磁盘、直连 SSH、可靠度至少 95%）。' if max_hourly is None else
                           f'当前价格上限内没有符合要求的 80 GB 单卡机器（{DISK_GB} GB 磁盘、直连 SSH、可靠度至少 95%）。')
    selected_id = os.environ.get('CLOUD_GPU_STUDIO_OFFER_ID')
    offer = next((item for item in offers if str(item['id']) == selected_id), None) if selected_id else offers[0]
    if offer is None:
        raise RuntimeError('选中的 Vast.ai 报价已下架或涨价，请刷新报价后重新选择；没有自动改选其他机器。')
    print(f"Selecting {offer['gpu_name']} at ${offer['dph_total']:.2f}/hour (offer {offer['id']}).", flush=True)
    # A timed-out create request is ambiguous: never try another offer automatically.
    created = request('asks/' + str(offer['id']) + '/',
                      {'image': IMAGE, 'label': 'cloud-gpu-studio', 'disk': DISK_GB,
                       'runtype': 'ssh_direct', 'cancel_unavail': True}, method='PUT')
    instance_id = created.get('new_contract')
    if not instance_id:
        raise RuntimeError('Vast.ai did not return an instance ID; inspect the console before retrying.')
    s = {'id': instance_id, 'created_epoch': time.time(), 'initial_balance': float(balance),
         'cost_per_hour': float(offer['dph_total']),
         'max_hourly': max_hourly,
         'gpu_type': offer['gpu_name'], 'offer_id': offer['id'], 'model': json.loads(selected_manifest.read_text())}
    save_state(s)
    try:
        with (WORK / 'vast-budget-guard.log').open('a') as log:
            subprocess.Popen([sys.executable, '-u', __file__, 'guard'], cwd=BASE,
                             stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        print(f'Created Vast.ai instance {instance_id}; waiting for direct SSH.', flush=True)
        for _ in range(90):
            current = instance()
            if current and max_hourly is not None and float(current.get('dph_total') or s['cost_per_hour']) > max_hourly:
                raise RuntimeError('Vast.ai 实际价格超过所选上限，正在删除机器。')
            if current and current.get('actual_status') in ('exited', 'unknown', 'offline'):
                raise RuntimeError('Vast.ai host failed during startup: ' + current['actual_status'])
            info = ssh_info(current) if current else None
            if info and subprocess.run(ssh_command(info, 'true'), capture_output=True, timeout=25).returncode == 0:
                break
            time.sleep(10)
        else:
            raise RuntimeError('Vast.ai SSH startup exceeded 15 minutes.')
        s['metrics_ssh'] = info
        save_state(s)
        print('GPU_SSH_READY', flush=True)
        subprocess.run(ssh_command(info, 'mkdir -p /workspace/bootstrap'), check=True)
        subprocess.run(['scp', *info['options'], '-P', info['port'],
                        str(DEPLOYABLE / 'setup_remote.sh'), str(DEPLOYABLE / 'download_models.py'),
                        info['host'] + ':/workspace/bootstrap/'], check=True)
        subprocess.run(['scp', *info['options'], '-P', info['port'], str(selected_manifest),
                        info['host'] + ':/workspace/bootstrap/models.lock.json'], check=True)
        total_gb = sum(item['size'] for item in s['model']['files']) / 1e9
        print(f'Installing ComfyUI and downloading {total_gb:.1f} GB of models.', flush=True)
        subprocess.run(ssh_command(info, 'bash /workspace/bootstrap/setup_remote.sh'), check=True, timeout=9000)
        print('Cloud ComfyUI is ready. Opening the SSH tunnel now.', flush=True)
    except BaseException:
        stop()
        raise


def resume():
    current = instance()
    if not current:
        raise RuntimeError('No tracked Vast.ai machine is available to resume.')
    print('Checking existing Vast.ai machine before continuing deployment...', flush=True)
    for _ in range(90):
        current = instance()
        info = ssh_info(current) if current else None
        if info and subprocess.run(ssh_command(info, 'true'), capture_output=True, timeout=25).returncode == 0:
            break
        time.sleep(10)
    else:
        raise RuntimeError('The existing Vast.ai machine did not become reachable by SSH.')
    s = state()
    s['metrics_ssh'] = info
    save_state(s)
    print('GPU_SSH_READY', flush=True)
    health = subprocess.run(ssh_command(info, 'curl -fsS --max-time 3 http://127.0.0.1:8188/system_stats'),
                            capture_output=True, timeout=25)
    if health.returncode == 0:
        print('CLOUD_READY', flush=True)
        return
    selected_manifest = manifest()
    subprocess.run(ssh_command(info, 'mkdir -p /workspace/bootstrap'), check=True)
    subprocess.run(['scp', *info['options'], '-P', info['port'],
                    str(DEPLOYABLE / 'setup_remote.sh'), str(DEPLOYABLE / 'download_models.py'),
                    info['host'] + ':/workspace/bootstrap/'], check=True)
    subprocess.run(['scp', *info['options'], '-P', info['port'], str(selected_manifest),
                    info['host'] + ':/workspace/bootstrap/models.lock.json'], check=True)
    print('Continuing installation and model download on the existing machine...', flush=True)
    subprocess.run(ssh_command(info, 'bash /workspace/bootstrap/setup_remote.sh'), check=True, timeout=9000)
    print('CLOUD_READY', flush=True)


def stop():
    instance_id = state().get('id')
    if not instance_id:
        print('No tracked Vast.ai instance.', flush=True)
        return
    if instance():
        try:
            request('instances/' + str(instance_id) + '/', method='DELETE')
        except RuntimeError as error:
            # The deployment worker may also be cleaning up the same instance.
            if 'HTTP 404' not in str(error):
                raise
    for _ in range(24):
        if not instance():
            save_state({})
            print('Vast.ai instance and disposable disk deleted. Local outputs are unchanged.', flush=True)
            return
        time.sleep(2)
    raise RuntimeError('Vast.ai deletion has not completed; check the console.')


def guard():
    s = state()
    if not s.get('id'):
        return
    while True:
        try:
            current = instance()
            if current is None:
                return
            elapsed = time.time() - s['created_epoch']
            price = float(current.get('dph_total') or s['cost_per_hour'])
            balance = available_funds()
            spent = s['initial_balance'] - balance
            limit = s.get('max_hourly')
            if spent >= 9 or elapsed * price / 3600 >= 9 or (limit is not None and price > limit):
                request('instances/' + str(s['id']) + '/', method='DELETE')
                print('Budget guard deleted Vast.ai instance.', flush=True)
                return
        except Exception as error:
            print(str(error)[:300], flush=True)
        time.sleep(30)


def connect():
    current = instance()
    if not current:
        raise RuntimeError('No Vast.ai GPU is running.')
    info = ssh_info(current)
    if not info:
        raise RuntimeError('Vast.ai SSH port is not ready.')
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
