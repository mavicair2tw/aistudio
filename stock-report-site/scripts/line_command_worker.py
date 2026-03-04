#!/usr/bin/env python3
"""Poll LINE command queue and trigger OpenClaw actions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / '.env'
LINE_SCRIPT = BASE_DIR / 'scripts' / 'notify_line.py'
TW_BRIEF = BASE_DIR / 'scripts' / 'send_tw_brief.py'
US_BRIEF = BASE_DIR / 'scripts' / 'send_us_brief.py'
COMMAND_ENDPOINT = 'https://line-webhook.googselect.workers.dev/commands'
ACK_ENDPOINT = 'https://line-webhook.googselect.workers.dev/commands/ack'


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


def request_json(url: str, token: str, *, data: dict | None = None) -> dict:
    headers = {
        'accept': 'application/json',
        'authorization': f'Bearer {token}'
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        headers['content-type'] = 'application/json'
    req = Request(url, data=body, headers=headers)
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def fetch_commands(token: str) -> list[dict]:
    try:
        payload = request_json(COMMAND_ENDPOINT, token)
        commands = payload.get('commands', [])
        return commands if isinstance(commands, list) else []
    except HTTPError as exc:
        print(f'Failed to fetch commands: {exc}')
    except URLError as exc:
        print(f'Command endpoint unreachable: {exc}')
    except Exception as exc:
        print(f'Unexpected error while fetching commands: {exc}')
    return []


def ack_commands(token: str, ids: Iterable[str]) -> None:
    ids = [i for i in ids if i]
    if not ids:
        return
    try:
        request_json(ACK_ENDPOINT, token, data={'ids': ids})
    except Exception as exc:
        print(f'Failed to ack commands: {exc}')


def run_brief(script: Path) -> bool:
    try:
        subprocess.run([sys.executable, str(script), '--skip-update'], check=True)
        return True
    except subprocess.CalledProcessError as exc:
        print(f'{script.name} failed: {exc}')
        return False


def handle_command(cmd: dict) -> bool:
    command = (cmd.get('command') or '').strip().upper()
    if not command:
        return True
    if command in {'TW', 'TW BRIEF', 'TW NOW'}:
        return run_brief(TW_BRIEF)
    if command in {'US', 'US BRIEF', 'US NOW'}:
        return run_brief(US_BRIEF)
    print(f'Unknown LINE command: {command}')
    return True


def main() -> None:
    load_env()
    token = os.environ.get('LINE_COMMAND_TOKEN')
    if not token:
        print('LINE_COMMAND_TOKEN missing; aborting')
        return

    commands = fetch_commands(token)
    if not commands:
        return

    processed: list[str] = []
    for cmd in commands:
        if handle_command(cmd):
            processed.append(cmd.get('id'))
    if processed:
        ack_commands(token, processed)


if __name__ == '__main__':
    main()
