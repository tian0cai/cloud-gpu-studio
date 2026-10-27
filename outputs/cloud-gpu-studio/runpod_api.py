"""Minimal RunPod API client; credentials stay in the local work directory."""
import json
import subprocess
import time

from app_config import SECRETS


def request(path, data=None, method=None, graphql=False):
    key_file = SECRETS / 'runpod_api_key'
    if not key_file.exists():
        raise RuntimeError('Save a RunPod API Key in the desktop app first.')
    key = key_file.read_text().strip()
    # A status poll should finish promptly even if a single API request hangs.
    is_read = (method is None or method.upper() == 'GET') and (
        (not graphql and data is None) or
        (graphql and isinstance(data, dict) and
         data.get('query', '').lstrip().lower().startswith('query')))
    url = 'https://api.runpod.io/graphql' if graphql else 'https://rest.runpod.io/v1/' + path
    command = ['curl', '--silent', '--show-error', '--max-time', '15' if is_read else '45', '--config', '-',
               url, '--write-out', '\n%{http_code}']
    config = 'header = "Authorization: Bearer ' + key + '"\nheader = "Content-Type: application/json"\n'
    if data is not None:
        command += ['--data', json.dumps(data)]
    if method:
        command += ['--request', method]
    # Status queries may briefly fail while RunPod is provisioning. Only
    # repeat reads: repeating a failed Pod creation or deletion is unsafe.
    attempts = 3 if is_read else 1
    for attempt in range(attempts):
        result = subprocess.run(command, input=config, text=True, capture_output=True)
        if result.returncode:
            error = RuntimeError(result.stderr.strip() or f'curl exited {result.returncode}')
            retryable = result.returncode in (6, 7, 28, 52, 56)
        else:
            try:
                body, status_text = result.stdout.rsplit('\n', 1)
                status = int(status_text)
                if not 200 <= status < 300:
                    error = RuntimeError('RunPod HTTP ' + str(status) + ': ' + body[:800])
                    retryable = status in (408, 429, 500, 502, 503, 504)
                else:
                    value = json.loads(body) if body else None
                    if isinstance(value, dict) and value.get('errors'):
                        raise RuntimeError(json.dumps(value['errors']))
                    return value
            except (ValueError, IndexError) as cause:
                error = RuntimeError('RunPod returned an invalid API response')
                retryable = True
        if attempt + 1 == attempts or not retryable:
            raise error
        time.sleep(attempt + 1)
    raise AssertionError('unreachable')


def gql(query):
    return request('', {'query': query}, graphql=True)['data']
