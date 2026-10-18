"""Install and maintain the local ComfyUI client without touching user workflows."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import getproxies


REPO = 'https://github.com/Comfy-Org/ComfyUI.git'
HOME = Path.home()
COMFY = Path(os.environ.get('CLOUD_GPU_STUDIO_COMFYUI_DIR', HOME / 'ComfyUI')).expanduser()
BRIDGE = Path(__file__).resolve().parent / 'comfyui_cloud_bridge'
WORKFLOW_TEMPLATES = Path(__file__).resolve().parent / 'workflows'


def compatible_bridge(path):
    module = path / '__init__.py'
    if not module.is_file():
        return False
    source = module.read_text(errors='replace')
    return 'CloudCheckpointImage' in source and 'CloudH3Video' in source


def network_env():
    env = os.environ.copy()
    proxies = getproxies()
    for scheme in ('http', 'https'):
        if not env.get(f'{scheme.upper()}_PROXY') and not env.get(f'{scheme}_proxy') and proxies.get(scheme):
            env[f'{scheme.upper()}_PROXY'] = proxies[scheme]
    return env


def run(*args, cwd=None, timeout=None):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, env=network_env())
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f'{args[0]} 退出码 {result.returncode}')
    return result.stdout.strip()


def python_for_venv():
    candidates = ('python3.12', 'python3.11', 'python3.13', 'python3.10', 'python3')
    for name in candidates:
        path = shutil.which(name)
        if not path:
            continue
        output = run(path, '-c', 'import sys; print(sys.version_info.major, sys.version_info.minor)')
        major, minor = map(int, output.split())
        if major == 3 and 10 <= minor <= 13:
            return path
    raise RuntimeError('需要 Python 3.10–3.13。请先安装 Python，再重试一键安装。')


def origin_is_official():
    if not (COMFY / '.git').exists():
        return False
    origin = run('git', 'remote', 'get-url', 'origin', cwd=COMFY)
    return origin.rstrip('/').removesuffix('.git') in {
        'https://github.com/Comfy-Org/ComfyUI',
        'git@github.com:Comfy-Org/ComfyUI',
        'https://github.com/comfyanonymous/ComfyUI',
        'git@github.com:comfyanonymous/ComfyUI',
    }


def state(check_remote=False):
    installed = (COMFY / 'main.py').is_file()
    venv = COMFY / '.venv' / 'bin' / 'python'
    linked = COMFY / 'custom_nodes' / 'comfyui_cloud_bridge'
    result = {
        'path': str(COMFY), 'installed': installed,
        'python_ready': venv.is_file(),
        'bridge_ready': compatible_bridge(linked),
        'git_ready': (COMFY / '.git').exists(), 'version': None,
        'update_available': None, 'error': None,
    }
    if result['git_ready']:
        try:
            result['version'] = run('git', 'rev-parse', '--short', 'HEAD', cwd=COMFY)
            if check_remote:
                if not origin_is_official():
                    raise RuntimeError('现有 ComfyUI 不是官方 Git 仓库，无法自动检查更新。')
                remote = run('git', 'ls-remote', REPO, 'HEAD', timeout=35).split()[0]
                local = run('git', 'rev-parse', 'HEAD', cwd=COMFY)
                result['update_available'] = remote != local
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            result['error'] = str(exc)
    return result


def say(message):
    print(message, flush=True)


def bridge_link():
    target = COMFY / 'custom_nodes' / 'comfyui_cloud_bridge'
    target.parent.mkdir(parents=True, exist_ok=True)
    if compatible_bridge(target):
        return
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        raise RuntimeError(f'已有同名自定义节点目录，请手动检查：{target}')
    target.symlink_to(BRIDGE, target_is_directory=True)


def install_workflows():
    destination = COMFY / 'user' / 'default' / 'workflows'
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('H3-单图首帧-FL2VA.json', 'H3-双图参考-Ref2VA.json'):
        source = WORKFLOW_TEMPLATES / name
        if not source.is_file():
            raise RuntimeError(f'安装包缺少工作流模板：{name}')
        target = destination / name
        if not target.exists() and not target.is_symlink():
            shutil.copyfile(source, target)


def install():
    if not shutil.which('git'):
        raise RuntimeError('未找到 Git。请先安装 Git 或 Xcode Command Line Tools。')
    if COMFY.exists() and not (COMFY / 'main.py').is_file():
        raise RuntimeError(f'安装目录已存在但不是 ComfyUI：{COMFY}')
    if not COMFY.exists():
        say('正在从官方仓库下载 ComfyUI…')
        subprocess.run(['git', 'clone', '--depth', '1', REPO, str(COMFY)], check=True, env=network_env())
    python = COMFY / '.venv' / 'bin' / 'python'
    if not python.is_file():
        say('正在创建 Python 虚拟环境…')
        run(python_for_venv(), '-m', 'venv', str(COMFY / '.venv'))
    say('正在安装 ComfyUI 依赖，首次下载可能需要几分钟…')
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(COMFY / 'requirements.txt')], cwd=COMFY, check=True, env=network_env())
    say('正在连接 Cloud GPU Studio 节点…')
    bridge_link()
    say('正在安装 H3 工作流模板…')
    install_workflows()
    say('本地 ComfyUI 已就绪。')


def update():
    if not (COMFY / 'main.py').is_file() or not origin_is_official():
        raise RuntimeError('只能自动更新官方 Git 仓库安装的 ComfyUI。')
    if run('git', 'status', '--porcelain', '--untracked-files=no', cwd=COMFY):
        raise RuntimeError('ComfyUI 主程序有本地改动，请先自行处理后再更新。')
    say('正在从官方仓库更新 ComfyUI…')
    subprocess.run(['git', 'pull', '--ff-only'], cwd=COMFY, check=True, env=network_env())
    install()
    say('更新完成。若 ComfyUI 正在运行，请重启应用后使用新版。')


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if command == 'status':
        print(json.dumps(state()))
    elif command == 'check':
        print(json.dumps(state(check_remote=True)))
    elif command == 'install':
        install()
    elif command == 'update':
        update()
    else:
        raise RuntimeError(f'未知操作：{command}')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f'本地 ComfyUI 操作失败：{error}', file=sys.stderr, flush=True)
        sys.exit(1)
