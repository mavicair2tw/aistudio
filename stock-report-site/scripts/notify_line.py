#!/usr/bin/env python3
"""Send a LINE push notification using channel credentials from .env."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"
LINE_TOKEN_URL = "https://api.line.me/v2/oauth/accessToken"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_SUBSCRIBERS_URL = "https://line-webhook.googselect.workers.dev/subscribers"


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def get_access_token(channel_id: str, channel_secret: str) -> str:
    payload = (
        "grant_type=client_credentials"
        f"&client_id={channel_id}"
        f"&client_secret={channel_secret}"
    ).encode()
    req = Request(LINE_TOKEN_URL, data=payload, headers={
        "content-type": "application/x-www-form-urlencoded"
    })
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to obtain LINE access token: {data}")
    return token


def push_message(token: str, user_id: str, text: str, image_url: str | None) -> None:
    messages = []
    if text:
        messages.append({"type": "text", "text": text})
    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        })
    if not messages:
        raise RuntimeError("Nothing to send to LINE")
    payload = json.dumps({
        "to": user_id,
        "messages": messages
    }).encode("utf-8")
    req = Request(LINE_PUSH_URL, data=payload, headers={
        "content-type": "application/json",
        "authorization": f"Bearer {token}"
    })
    try:
        with urlopen(req, timeout=10) as resp:
            resp.read()
    except HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"LINE push failed: {exc.code} {detail}")
    except URLError as exc:
        raise RuntimeError(f"LINE push connection error: {exc}")



def get_subscriber_ids() -> list[str]:
    headers = {
        "accept": "application/json",
        "user-agent": "line-bot/1.0"
    }
    req = Request(LINE_SUBSCRIBERS_URL, headers=headers)
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    ids = data.get("ids", [])
    if not isinstance(ids, list):
        return []
    return [item for item in ids if isinstance(item, str)]


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Send a LINE push notification")
    parser.add_argument("text", help="Message text")
    parser.add_argument("--image-url", help="Optional image URL to send")
    args = parser.parse_args(argv)

    load_env()
    channel_id = os.environ.get("LINE_CHANNEL_ID")
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET")
    fallback_user = os.environ.get("LINE_USER_ID")
    if not channel_id or not channel_secret:
        raise SystemExit("Missing LINE_CHANNEL_ID / LINE_CHANNEL_SECRET")

    token = get_access_token(channel_id, channel_secret)
    targets: list[str] = []
    if fallback_user:
        targets.append(fallback_user)
    try:
        subscribers = get_subscriber_ids()
        for subscriber in subscribers:
            if subscriber not in targets:
                targets.append(subscriber)
    except Exception as exc:
        print(f"Warning: failed to fetch LINE subscribers: {exc}")

    if not targets:
        raise SystemExit("No LINE recipients available")

    for target in targets:
        push_message(token, target, args.text, args.image_url)
    print(f"Sent LINE push to {len(targets)} recipient(s)")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as exc:
        raise SystemExit(f"Error: {exc}")
