"""Route desktop actions to the selected provider without losing an active deployment."""
import json
import subprocess
import sys
from pathlib import Path

from app_config import WORK, REF2VA_READY, FL2VA_READY, read, validate_local_pack

ACTIVE = WORK / 'active-provider.json'
HERE = Path(__file__).resolve().parent


def active_provider():
    return json.loads(ACTIVE.read_text())['provider'] if ACTIVE.exists() else None


def provider():
    return active_provider() or read()['provider']


def run(command, chosen=None):
    name = chosen or provider()
    target = HERE / ('vast_control.py' if name == 'vast' else 'runpod_control.py')
    return subprocess.run([sys.executable, '-u', str(target), command])


def prepare_mode(mode):
    chosen = active_provider()
    if not chosen:
        raise RuntimeError('请先启动并连接云端机器。')
    if read()['video_model'] == 'none':
        raise RuntimeError('当前配置没有部署 H3 视频模型。')
    if chosen == 'vast':
        import vast_control as control
        current = control.instance()
        machine_id = (current or {}).get('id')
        info = control.ssh_info(current) if current else None
    else:
        import runpod_control as control
        current = control.current_pod()
        machine_id = (current or {}).get('id')
        info = control.ssh_info(machine_id) if machine_id else None
    if not machine_id or not info:
        raise RuntimeError('云端机器或 SSH 连接尚未就绪。')
    if mode == 'ref2va':
        files = json.loads((HERE / 'ref2va.lock.json').read_text())['files']
        marker_path = REF2VA_READY
    else:
        settings = read()
        source = (validate_local_pack()[0] if settings['video_model'] == 'local-h3'
                  else json.loads((HERE / 'models.lock.json').read_text())['files'])
        files = [item for item in source if item.get('preset') == 'h3'
                 and (item['destination'].startswith('diffusion_models/')
                      or item['destination'].startswith('loras/'))]
        marker_path = FL2VA_READY
    if not files:
        raise RuntimeError('No files found for the selected H3 mode.')
    manifest_file = WORK / (mode + '-download.lock.json')
    manifest_file.write_text(json.dumps({'files': files}) + '\n')
    manifest_file.chmod(0o600)
    print(f'Uploading pinned {mode.upper()} manifest...', flush=True)
    subprocess.run(['scp', *info['options'], '-P', info['port'], str(manifest_file),
                    info['host'] + f':/workspace/bootstrap/{mode}-download.lock.json'], check=True)
    print(f'Downloading and verifying {mode.upper()} model while current mode stays available...', flush=True)
    subprocess.run(control.ssh_command(info,
                   'python -u /workspace/bootstrap/download_models.py '
                   f'/workspace/bootstrap/{mode}-download.lock.json /workspace/ComfyUI/models'),
                   check=True, timeout=9000)
    marker = {'provider': chosen, 'id': str(machine_id)}
    temporary = marker_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(marker) + '\n')
    temporary.replace(marker_path)
    print(mode.upper() + '_READY', flush=True)


def main():
    command = sys.argv[1]
    if command == 'status':
        chosen = provider()
        target = HERE / ('vast_control.py' if chosen == 'vast' else 'runpod_control.py')
        result = subprocess.run([sys.executable, '-u', str(target), 'status'],
                                text=True, capture_output=True)
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            return result.returncode
        value = json.loads(result.stdout)
        value['provider'] = chosen
        if value.get('pod') and not active_provider():
            ACTIVE.write_text(json.dumps({'provider': chosen}) + '\n')
        elif not value.get('pod') and active_provider():
            ACTIVE.unlink(missing_ok=True)
        print(json.dumps(value))
        return 0
    if command == 'offers':
        return run('offers', read()['provider']).returncode
    if command == 'metrics':
        from host_metrics import collect
        print(json.dumps(collect(provider())))
        return 0
    if command == 'prepare-ref2va':
        prepare_mode('ref2va')
        return 0
    if command == 'prepare-fl2va':
        prepare_mode('fl2va')
        return 0
    if command == 'start':
        selected = read()['provider']
        if active_provider() and active_provider() != selected:
            raise RuntimeError('Delete the current cloud machine before switching providers.')
        ACTIVE.write_text(json.dumps({'provider': selected}) + '\n')
        result = run(command, selected)
        if result.returncode == 0 and read()['video_model'] != 'none':
            state = json.loads((WORK / ('vast-deployment.json' if selected == 'vast' else 'deployment.json')).read_text())
            machine_id = state.get('id') if selected == 'vast' else (state.get('pod') or {}).get('id')
            if machine_id:
                marker = REF2VA_READY if read()['video_mode'] == 'ref2va' else FL2VA_READY
                marker.write_text(json.dumps({'provider': selected, 'id': str(machine_id)}) + '\n')
        return result.returncode
    result = run(command)
    if command == 'stop' and result.returncode == 0:
        ACTIVE.unlink(missing_ok=True)
    return result.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
