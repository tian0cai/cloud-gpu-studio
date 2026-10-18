"""Minimal RunPod API client; credentials stay in the local work directory."""
import json
import subprocess

from app_config import SECRETS


def request(path, data=None, method=None, graphql=False):
    key_file = SECRETS / 'runpod_api_key'
    if not key_file.exists():
        raise RuntimeError('Save a RunPod API Key in the desktop app first.')
    key = key_file.read_text().strip()
    url = 'https://api.runpod.io/graphql' if graphql else 'https://rest.runpod.io/v1/' + path
    command = ['curl', '--silent', '--show-error', '--max-time', '45', '--config', '-',
               url, '--write-out', '\n%{http_code}']
    config = 'header = "Authorization: Bearer ' + key + '"\nheader = "Content-Type: application/json"\n'
    if data is not None:
        command += ['--data', json.dumps(data)]
    if method:
        command += ['--request', method]
    result = subprocess.run(command, input=config, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    body, status = result.stdout.rsplit('\n', 1)
    if not 200 <= int(status) < 300:
        raise RuntimeError('RunPod HTTP ' + status + ': ' + body[:800])
    value = json.loads(body) if body else None
    if isinstance(value, dict) and value.get('errors'):
        raise RuntimeError(json.dumps(value['errors']))
    return value


def gql(query):
    return request('', {'query': query}, graphql=True)['data']
