#!/usr/bin/env python3
"""Create a disposable RunPod GPU, bootstrap it, and connect through SSH."""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from runpod_api import gql, request
from app_config import BASE, WORK, SECRETS, manifest

STATE = WORK / 'deployment.json'
DEPLOYABLE = Path(__file__).resolve().parent
GPU_TYPES = ('NVIDIA A100-SXM4-80GB', 'NVIDIA A100 80GB PCIe')
DATACENTERS = ('CA-MTL-3', 'EUR-IS-1', 'US-KS-2', 'US-MD-1')
IMAGE = 'runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04'
VOLUME_GB = 180  # Room for both H3 modes, image models, downloads and outputs.


def ensure_ssh_key():
    private = SECRETS / 'runpod_ed25519'
    public = SECRETS / 'runpod_ed25519.pub'
    if private.exists() and public.exists():
        return
    if private.exists() or public.exists():
        raise RuntimeError('SSH key pair is incomplete; inspect the local secrets directory.')
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o700)
    SECRETS.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS, 0o700)
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(private)], check=True)
    os.chmod(private, 0o600)


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(value):
    WORK.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(value, indent=2) + '\n')


def find_pod(pid):
    return next((pod for pod in request('pods') if pod['id'] == pid), None) if pid else None


def current_pod():
    return find_pod(state().get('pod', {}).get('id'))


def ssh_info(pod_id):
    pod = gql('query { pod(input: {podId: ' + json.dumps(pod_id) + '}) { runtime { ports { ip isIpPublic privatePort publicPort } } } }')['pod']
    ports = (pod.get('runtime') or {}).get('ports', []) if pod else []
    port = next((p for p in ports if p['isIpPublic'] and p['privatePort'] == 22), None)
    if not port:
        return None
    known_hosts = WORK / 'secrets' / ('known_hosts_' + pod_id)
    options = ['-i', str(WORK / 'secrets/runpod_ed25519'), '-o', 'StrictHostKeyChecking=accept-new',
               '-o', 'UserKnownHostsFile=' + str(known_hosts), '-o', 'ConnectTimeout=15',
               '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3']
    return {'port': str(port['publicPort']), 'host': 'root@' + port['ip'], 'options': options}


def ssh_command(info, *remote):
    return ['ssh', *info['options'], '-p', info['port'], info['host'], *remote]


def stop():
    pid = state().get('pod', {}).get('id')
    if not pid:
        print('No tracked GPU Pod.')
        return
    if current_pod():
        request('pods/' + pid, method='DELETE')
    for _ in range(24):
        if not current_pod():
            print('GPU Pod and its disposable volume deleted. Local images and videos are unchanged.')
            return
        time.sleep(2)
    raise RuntimeError('Deletion has not completed; check RunPod console and run status again.')


def guard():
    s = state()
    pid = s['pod']['id']
    while True:
        try:
            pod = find_pod(pid)
            if pod is None:
                return
            balance = gql('query { myself { clientBalance } }')['myself']['clientBalance']
            limit = s.get('max_hourly')
            if (time.time() >= s['created_epoch'] + 10800
                    or balance <= s['initial_balance'] - 9
                    or (limit is not None and float(pod.get('costPerHr') or 0) > limit)):
                request('pods/' + pid, method='DELETE')
                print('Guard deleted the Pod and disposable volume.', flush=True)
                return
        except Exception as error:
            print(str(error)[:300], flush=True)
        time.sleep(30)


def graphql_value(value):
    if isinstance(value, dict):
        return '{' + ', '.join(k + ': ' + graphql_value(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(graphql_value(v) for v in value) + ']'
    return json.dumps(value)


def quote_gpu(dc, gpu):
    query = ('query { gpuTypes(input: {id: ' + json.dumps(gpu)
             + '}) { lowestPrice(input: {gpuCount: 1, secureCloud: true, dataCenterId: '
             + json.dumps(dc)
             + ', minMemoryInGb: 96, supportPublicIp: true}) { uninterruptablePrice stockStatus } } }')
    return gql(query)['gpuTypes'][0]['lowestPrice']


def selected_price_limit():
    raw = os.environ.get('CLOUD_GPU_STUDIO_MAX_HOURLY')
    if not raw:
        return None
    value = float(raw)
    if not 0 < value < float('inf'):
        raise RuntimeError('每小时价格上限必须是高于 $0 的有限数字。')
    return value


def offer_catalog(max_hourly):
    base_query = ('query { gpuTypes { id memoryInGb lowestPrice(input: '
                  '{gpuCount: 1, secureCloud: true, minMemoryInGb: 96, supportPublicIp: true}) '
                  '{ uninterruptablePrice stockStatus } } }')
    types = []
    for item in gql(base_query)['gpuTypes']:
        price = (item.get('lowestPrice') or {}).get('uninterruptablePrice')
        if (item['id'].startswith('NVIDIA ') and (item.get('memoryInGb') or 0) >= 80
                and price is not None and float(price) > 0
                and (max_hourly is None or float(price) <= max_hourly)):
            types.append(item)
    if not types:
        return []
    centers = [item['id'] for item in gql('query { dataCenters { id } }')['dataCenters']]
    pairs = [(gpu, dc) for gpu in types for dc in centers]
    found = []
    for offset in range(0, len(pairs), 35):
        batch = pairs[offset:offset + 35]
        fields = []
        for index, (gpu, dc) in enumerate(batch):
            fields.append('q' + str(index) + ': gpuTypes(input: {id: ' + json.dumps(gpu['id'])
                          + '}) { lowestPrice(input: {gpuCount: 1, secureCloud: true, dataCenterId: '
                          + json.dumps(dc) + ', minMemoryInGb: 96, supportPublicIp: true}) '
                          + '{ uninterruptablePrice stockStatus } }')
        result = gql('query { ' + ' '.join(fields) + ' }')
        for index, (gpu, dc) in enumerate(batch):
            rows = result.get('q' + str(index)) or []
            quote = (rows[0].get('lowestPrice') or {}) if rows else {}
            price = quote.get('uninterruptablePrice')
            if (price is not None and float(price) > 0
                    and (max_hourly is None or float(price) <= max_hourly)
                    and quote.get('stockStatus') not in (None, 'None')):
                found.append({'id': gpu['id'] + '|' + dc, 'gpu': gpu['id'],
                              'price': float(price), 'location': dc,
                              'vramGb': float(gpu['memoryInGb']), 'reliability': None})
    found.sort(key=lambda item: (item['price'], item['gpu'], item['location']))
    visible = found[:100]
    visible_models = {item['gpu'] for item in visible}
    for item in found[100:]:
        if item['gpu'] not in visible_models:
            visible.append(item)
            visible_models.add(item['gpu'])
    return sorted(visible, key=lambda item: (item['price'], item['gpu'], item['location']))


def start():
    s = state()
    selected_manifest = manifest()
    if current_pod():
        raise RuntimeError('GPU already exists. Use 仅连接云端.command to reconnect.')
    balance = gql('query { myself { clientBalance } }')['myself']['clientBalance']
    if balance < 10:
        raise RuntimeError('Less than $10 remains; check the RunPod account first.')
    created = time.time()
    deadline = datetime.datetime.fromtimestamp(created + 10800, datetime.timezone.utc).isoformat()
    ensure_ssh_key()
    public_key = (SECRETS / 'runpod_ed25519.pub').read_text().strip()
    max_hourly = selected_price_limit()
    selected_id = os.environ.get('CLOUD_GPU_STUDIO_OFFER_ID')
    if selected_id:
        offer = next((item for item in offer_catalog(max_hourly) if item['id'] == selected_id), None)
        if offer is None:
            raise RuntimeError('选中的 RunPod 报价已无库存或涨价，请刷新报价后重新选择；没有自动改选其他机器。')
        candidates = [(offer['gpu'], offer['location'])]
    else:
        candidates = [(gpu, dc) for gpu in GPU_TYPES for dc in DATACENTERS]
    pod = None
    for gpu, dc in candidates:
        quote = quote_gpu(dc, gpu)
        if (not quote or quote.get('uninterruptablePrice') is None
                or float(quote['uninterruptablePrice']) <= 0
                or (max_hourly is not None and float(quote['uninterruptablePrice']) > max_hourly)
                or quote.get('stockStatus') in (None, 'None')):
            continue
        args = {
            'cloudType': 'SECURE', 'gpuCount': 1, 'gpuTypeId': gpu, 'dataCenterId': dc,
            'containerDiskInGb': 30, 'volumeInGb': VOLUME_GB, 'volumeMountPath': '/workspace',
            'minMemoryInGb': 96, 'minVcpuCount': 8, 'name': 'cloud-gpu-studio-disposable',
            'imageName': IMAGE, 'ports': '22/tcp', 'startSsh': True, 'startJupyter': False,
            'supportPublicIp': True, 'terminateAfter': deadline,
            'env': [{'key': 'PUBLIC_KEY', 'value': public_key}],
        }
        body = graphql_value(args).replace('cloudType: "SECURE"', 'cloudType: SECURE')
        try:
            pod = gql('mutation { podFindAndDeployOnDemand(input: ' + body
                      + ') { id name costPerHr desiredStatus } }')['podFindAndDeployOnDemand']
            break
        except RuntimeError as error:
            # SUPPLY_CONSTRAINT explicitly means no Pod was created. A network error is
            # ambiguous, so never retry it automatically: it could create duplicates.
            if 'SUPPLY_CONSTRAINT' not in str(error):
                raise
            if selected_id:
                raise RuntimeError('选中的 RunPod 机器在创建前售罄，请刷新报价后重新选择。') from error
            print(f'{dc} {gpu}: stock disappeared; trying another location.', flush=True)
    if pod is None:
        raise RuntimeError('当前没有可创建的 RunPod 80 GB 显卡。' if max_hourly is None else
                           '当前价格上限内没有可创建的 RunPod 80 GB 显卡。')
    s.update(pod=pod, created_epoch=created, initial_balance=balance, gpu_type=gpu, data_center_id=dc,
             deadline=deadline, quote=quote, storage_mode='disposable', volume_size_gb=VOLUME_GB,
             max_hourly=max_hourly)
    save_state(s)
    try:
        if max_hourly is not None and float(pod['costPerHr']) > max_hourly:
            raise RuntimeError('RunPod 实际价格超过所选上限，正在删除机器。')
        with (WORK / 'budget-guard.log').open('a') as log:
            subprocess.Popen([sys.executable, '-u', __file__, 'guard'], cwd=BASE,
                             stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"Created {pod['id']} at ${pod['costPerHr']}/hour; waiting for SSH.", flush=True)
        for _ in range(90):
            info = ssh_info(pod['id'])
            if info and subprocess.run(ssh_command(info, 'true'), capture_output=True, timeout=25).returncode == 0:
                break
            time.sleep(10)
        else:
            raise RuntimeError('SSH startup exceeded 15 minutes.')
        s['metrics_ssh'] = info
        save_state(s)
        print('GPU_SSH_READY', flush=True)
        subprocess.run(ssh_command(info, 'mkdir -p /workspace/bootstrap'), check=True)
        scp = ['scp', *info['options'], '-P', info['port'],
               str(DEPLOYABLE / 'setup_remote.sh'), str(DEPLOYABLE / 'download_models.py'),
               info['host'] + ':/workspace/bootstrap/']
        subprocess.run(scp, check=True)
        subprocess.run(['scp', *info['options'], '-P', info['port'], str(selected_manifest),
                        info['host'] + ':/workspace/bootstrap/models.lock.json'], check=True)
        total_gb = sum(item['size'] for item in json.loads(selected_manifest.read_text())['files']) / 1e9
        print(f'Installing ComfyUI and downloading {total_gb:.1f} GB of models; this can take tens of minutes.', flush=True)
        subprocess.run(ssh_command(info, 'bash /workspace/bootstrap/setup_remote.sh'), check=True, timeout=9000)
        print('Cloud ComfyUI is ready. Opening the SSH tunnel now.', flush=True)
    except BaseException:
        stop()
        raise


def connect():
    pod = current_pod()
    if not pod:
        raise RuntimeError('No cloud GPU is running. Use 启动云端并连接.command first.')
    info = ssh_info(pod['id'])
    if not info:
        raise RuntimeError('Cloud SSH port is not ready yet.')
    command = ['ssh', *info['options'], '-p', info['port'], '-N', '-L',
               '127.0.0.1:8189:127.0.0.1:8188', '-o', 'ExitOnForwardFailure=yes', info['host']]
    subprocess.run(command, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Disposable RunPod GPU deployment')
    parser.add_argument('command', choices=['status', 'offers', 'start', 'stop', 'connect', 'guard'])
    command = parser.parse_args().command
    if command == 'status':
        s = state()
        pod = current_pod()
        old_id = s.get('volume', {}).get('id')
        old_volume = next((v for v in request('networkvolumes') if v['id'] == old_id), None) if old_id else None
        print(json.dumps({'pod': pod, 'storage_mode': s.get('storage_mode', 'network_volume'),
                          'old_network_volume_still_billed': old_volume,
                          'balance': gql('query { myself { clientBalance } }')['myself']['clientBalance']}, indent=2))
    elif command == 'offers':
        print(json.dumps(offer_catalog(selected_price_limit())))
    else:
        {'start': start, 'stop': stop, 'connect': connect, 'guard': guard}[command]()
