"""Read-only CPU, RAM and NVIDIA GPU telemetry over the provider's SSH connection."""
import json
import os
import shlex
import subprocess
from pathlib import Path


REMOTE_PROBE = r'''
import json
import os
import subprocess
import time

def read_number(path):
    try:
        return int(open(path).read().strip())
    except (OSError, ValueError):
        return None

def container_cpu():
    stat = '/sys/fs/cgroup/cpu.stat'
    if os.path.isfile(stat):
        values = dict(line.split() for line in open(stat))
        usage = int(values['usage_usec']) / 1_000_000
        quota, period = open('/sys/fs/cgroup/cpu.max').read().split()
        cores = float(quota) / float(period) if quota != 'max' else os.cpu_count()
        return usage, cores
    usage = read_number('/sys/fs/cgroup/cpuacct/cpuacct.usage')
    quota = read_number('/sys/fs/cgroup/cpu/cpu.cfs_quota_us')
    period = read_number('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
    if usage is not None and quota and quota > 0 and period:
        return usage / 1_000_000_000, quota / period
    return None

def cpu_ticks():
    with open('/proc/stat') as stream:
        values = [int(value) for value in stream.readline().split()[1:]]
    return sum(values), values[3] + values[4]

before_total, before_idle = cpu_ticks()
before_container = container_cpu()
sample_started = time.monotonic()
time.sleep(0.25)
after_total, after_idle = cpu_ticks()
after_container = container_cpu()
sample_seconds = time.monotonic() - sample_started
total_delta = after_total - before_total
cpu_percent = round(100 * (1 - (after_idle - before_idle) / total_delta), 1) if total_delta > 0 else None
if before_container and after_container and before_container[1] > 0:
    cpu_percent = round(min(100, max(0, 100 * (after_container[0] - before_container[0]) /
                                  (sample_seconds * before_container[1]))), 1)

with open('/proc/meminfo') as stream:
    memory = {parts[0].rstrip(':'): int(parts[1]) for line in stream if (parts := line.split())}
ram_total = memory['MemTotal'] / 1048576
ram_used = (memory['MemTotal'] - memory['MemAvailable']) / 1048576
limit = read_number('/sys/fs/cgroup/memory.max')
usage = read_number('/sys/fs/cgroup/memory.current')
if limit is None or usage is None:
    limit = read_number('/sys/fs/cgroup/memory/memory.limit_in_bytes')
    usage = read_number('/sys/fs/cgroup/memory/memory.usage_in_bytes')
if limit and usage is not None and limit < memory['MemTotal'] * 1024:
    ram_total, ram_used = limit / 1073741824, usage / 1073741824
result = {'cpuPercent': cpu_percent, 'ramUsedGb': round(ram_used, 2),
          'ramTotalGb': round(ram_total, 2), 'gpuPercent': None,
          'vramUsedGb': None, 'vramTotalGb': None}
try:
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total',
                          '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=4)
    if gpu.returncode == 0 and gpu.stdout.strip():
        utilization, used, total = [float(item.strip()) for item in gpu.stdout.splitlines()[0].split(',')]
        result.update(gpuPercent=utilization, vramUsedGb=round(used / 1024, 2),
                      vramTotalGb=round(total / 1024, 2))
except (OSError, ValueError, subprocess.TimeoutExpired):
    pass
print(json.dumps(result))
'''


def collect(provider):
    if provider in ('vast', 'vultr'):
        if provider == 'vast':
            import vast_control as cloud
        else:
            import vultr_control as cloud
        saved = cloud.state()
        if not saved.get('id'):
            return {'online': False}
        info = saved.get('metrics_ssh')
        if not info:
            current = cloud.instance()
            info = cloud.ssh_info(current) if current else None
    else:
        import runpod_control as cloud
        saved = cloud.state()
        pod_id = saved.get('pod', {}).get('id')
        if not pod_id:
            return {'online': False}
        info = saved.get('metrics_ssh')
        if not info:
            current = cloud.current_pod()
            info = cloud.ssh_info(current['id']) if current else None
    if not info:
        return {'online': False}
    command = cloud.ssh_command(info, 'python3 -c ' + shlex.quote(REMOTE_PROBE))
    # A short-lived control master avoids a new SSH handshake for every sample.
    socket_dir = Path('/private/tmp') / f'cgs-ssh-{os.getuid()}'
    socket_dir.mkdir(mode=0o700, exist_ok=True)
    if socket_dir.stat().st_uid != os.getuid():
        raise RuntimeError('Telemetry SSH socket directory is not owned by the current user.')
    socket = str(socket_dir / '%C')
    command[1:1] = ['-o', 'ControlMaster=auto', '-o', 'ControlPersist=30',
                    '-o', 'ControlPath=' + socket]
    try:
        response = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return {'online': False, 'message': '远程指标读取超时'}
    if response.returncode:
        return {'online': False, 'message': '远程指标暂不可用'}
    value = json.loads(response.stdout)
    return {'online': True, **value}


if __name__ == '__main__':
    import sys
    print(json.dumps(collect(sys.argv[1])))
