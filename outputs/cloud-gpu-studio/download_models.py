import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def download(item, root):
    dest = root / item['destination']
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.stat().st_size != item['size']:
        partial = dest.with_name(dest.name + '.part')
        url = 'https://huggingface.co/' + item['repo'] + '/resolve/' + item['revision'] + '/' + item['filename']
        print('Downloading ' + item['destination'], flush=True)
        subprocess.run(['curl', '-fsSL', '--retry', '5', '--retry-delay', '3', '--connect-timeout', '30', '--speed-time', '120', '--speed-limit', '100000', '-C', '-', '-o', str(partial), url], check=True)
        if partial.stat().st_size != item['size']:
            raise RuntimeError('Size mismatch: ' + str(partial))
        source = partial
    else:
        source = dest
    print('SHA256 ' + item['destination'], flush=True)
    h = hashlib.sha256()
    with source.open('rb') as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b''):
            h.update(b)
    if h.hexdigest() != item['sha256']:
        raise RuntimeError('Checksum mismatch: ' + str(source))
    if source != dest:
        os.replace(source, dest)
    print('Verified ' + item['destination'], flush=True)


if __name__ == '__main__':
    manifest = json.loads(Path(sys.argv[1]).read_text())
    root = Path(sys.argv[2])
    total = sum(item['size'] for item in manifest['files'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download, item, root) for item in manifest['files']]
        pending = set(futures)
        while pending:
            done, pending = concurrent.futures.wait(pending, timeout=20,
                                                     return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                future.result()
            obtained = 0
            for item in manifest['files']:
                target = root / item['destination']
                partial = target.with_name(target.name + '.part')
                obtained += min(item['size'], target.stat().st_size if target.exists()
                                else partial.stat().st_size if partial.exists() else 0)
            print(f'Model data: {obtained / 2**30:.1f} / {total / 2**30:.1f} GiB '
                  f'({100 * obtained / total:.0f}%)', flush=True)
    print('ALL_MODELS_VERIFIED', flush=True)
