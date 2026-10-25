"""Download pinned model files with Hugging Face Xet and verify their bytes."""

import concurrent.futures
import hashlib
import json
import os
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download


def staging_path(item, root):
    identity = f"{item['repo']}\0{item['revision']}\0{item['filename']}"
    directory = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return root / '.cloud-gpu-downloads' / directory


def verify(path, item):
    if path.stat().st_size != item['size']:
        raise RuntimeError('Size mismatch: ' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != item['sha256']:
        raise RuntimeError('Checksum mismatch: ' + str(path))


def download(item, root):
    dest = root / item['destination']
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            verify(dest, item)
            print('Verified existing ' + item['destination'], flush=True)
            return
        except RuntimeError:
            print('Replacing invalid existing file: ' + item['destination'], flush=True)

    # A separate local_dir per manifest entry prevents filename collisions.
    # Hugging Face keeps resumable download metadata in this directory.
    stage = staging_path(item, root)
    stage.mkdir(parents=True, exist_ok=True)
    print('Downloading with hf_xet: ' + item['destination'], flush=True)
    source = Path(hf_hub_download(
        repo_id=item['repo'], filename=item['filename'],
        revision=item['revision'], local_dir=stage,
    ))
    print('SHA256 ' + item['destination'], flush=True)
    verify(source, item)
    os.replace(source, dest)
    print('Verified ' + item['destination'], flush=True)


def downloaded_bytes(item, root):
    dest = root / item['destination']
    if dest.exists() and dest.stat().st_size == item['size']:
        return item['size']
    stage = staging_path(item, root) / item['filename']
    if stage.exists():
        return min(item['size'], stage.stat().st_size)
    # huggingface_hub writes Xet data to an .incomplete file under its local
    # metadata directory, then moves it into place. Include that file so the
    # deployment progress continues moving while a large model transfers.
    temporary_dir = staging_path(item, root) / '.cache/huggingface/download' / Path(item['filename']).parent
    if temporary_dir.exists():
        incomplete = (path.stat().st_size for path in temporary_dir.glob('*.incomplete'))
        return min(item['size'], max(incomplete, default=0))
    return 0


def main(manifest_path, root):
    manifest = json.loads(Path(manifest_path).read_text())
    root = Path(root)
    total = sum(item['size'] for item in manifest['files'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download, item, root) for item in manifest['files']]
        pending = set(futures)
        while pending:
            done, pending = concurrent.futures.wait(
                pending, timeout=20,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in done:
                future.result()
            obtained = sum(downloaded_bytes(item, root) for item in manifest['files'])
            percent = 100 if not pending else min(99, round(100 * obtained / total))
            print(f'Model data: {obtained / 2**30:.1f} / {total / 2**30:.1f} GiB '
                  f'({percent}%)', flush=True)
    print('ALL_MODELS_VERIFIED', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
