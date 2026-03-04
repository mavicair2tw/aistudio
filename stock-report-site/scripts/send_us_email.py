#!/usr/bin/env python3
"""Send the latest US market report to the configured mailbox."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import subprocess
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "data" / "us_latest.json"
ENV_FILE = BASE_DIR / ".env"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
LINE_SCRIPT = BASE_DIR / "scripts" / "notify_line.py"

REPORT_TITLE = "美股每日報告"
SUMMARY_PREFIX = "【美股摘要】"
SUGGESTION_PREFIX = "【投資建議】"
DISCLAIMER = "※ 程式自動摘要，僅供參考，非投資建議。"


@dataclass
class EmailConfig:
    user: str
    password: str
    recipient: str
    sender_name: str


class ConfigError(RuntimeError):
    pass


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def resolve_email_config(args: argparse.Namespace) -> EmailConfig:
    load_env_file(ENV_FILE)
    user = args.gmail_user or os.environ.get("GMAIL_USER")
    password = args.gmail_app_password or os.environ.get("GMAIL_APP_PASSWORD")
    recipient = args.to or os.environ.get("MAIL_TO_DEFAULT")
    sender_name = os.environ.get("MAIL_FROM_NAME", "OpenClaw")

    missing = [label for label, value in {
        "GMAIL_USER": user,
        "GMAIL_APP_PASSWORD": password,
        "MAIL_TO_DEFAULT / --to": recipient
    }.items() if not value]
    if missing:
        raise ConfigError(f"Missing required config: {', '.join(missing)}")

    return EmailConfig(user=user, password=password, recipient=recipient, sender_name=sender_name)


def load_latest() -> Mapping:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"US report not found at {DATA_PATH}")
    with DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def fmt_number(value: float | int) -> str:
    return f"{float(value):,.2f}".rstrip("0").rstrip(".")


def fmt_signed(value: float | int, suffix: str = "") -> str:
    return f"{float(value):+,.2f}".rstrip("0").rstrip(".") + suffix


def build_rows(items: Iterable[Mapping]) -> list[dict]:
    rows = []
    for item in items:
        rows.append({
            "label": item.get("label", ""),
            "symbol": item.get("symbol", ""),
            "price": fmt_number(item.get("price", 0)),
            "change": fmt_signed(item.get("change", 0)),
            "change_percent": fmt_signed(item.get("changePercent", 0), "%")
        })
    return rows


def build_line_table(rows: list[dict]) -> str:
    lines = ["股名 成交 漲跌 漲幅 代號"]
    for r in rows:
        lines.append(f"{r['label']} {r['price']} {r['change']} {r['change_percent']} {r['symbol']}")
    return "\n".join(lines)


def build_summary(items: Iterable[Mapping]) -> tuple[str, str]:
    valid = [i for i in items if isinstance(i.get("changePercent"), (int, float))]
    if not valid:
        summary = f"{SUMMARY_PREFIX}目前資料不足，建議先觀察。"
        suggestion = f"{SUGGESTION_PREFIX}暫時觀望盤勢，等待更多資訊。"
        return summary, suggestion

    avg = sum(i["changePercent"] for i in valid) / len(valid)
    up = sum(1 for i in valid if i["changePercent"] > 0)
    down = sum(1 for i in valid if i["changePercent"] < 0)
    top_up = max(valid, key=lambda i: i["changePercent"])
    top_down = min(valid, key=lambda i: i["changePercent"])

    tone = "中性偏觀望"
    action = "建議分批、控制部位，等待方向更明確。"
    if avg > 0.6 and up > down:
        tone = "偏多"
        action = "可優先關注強勢標的，採分批布局並設停利停損。"
    elif avg < -0.6 and down >= up:
        tone = "偏空"
        action = "建議降低追價，保留現金，等待止穩訊號。"

    strong = fmt_signed(top_up['changePercent'], '%')
    weak = fmt_signed(top_down['changePercent'], '%')
    summary = (
        f"{SUMMARY_PREFIX}整體氣氛：{tone}（平均漲幅 {avg:.2f}% ，上漲 {up} 檔 / 下跌 {down} 檔）。"
        f"強勢：{top_up['label']} ({strong})，弱勢：{top_down['label']} ({weak})。"
    )
    suggestion = f"{SUGGESTION_PREFIX}{action}"
    return summary, suggestion


def build_html(sent_at: str, data_timestamp: str, rows: list[dict], summary: str, suggestion: str) -> str:
    table_rows = "".join(
        f"<tr>"
        f"<td>{r['label']}<br/><span style='color:#666;font-size:12px;'>{r['symbol']}</span></td>"
        f"<td style='text-align:right;'>{r['price']}</td>"
        f"<td style='text-align:right;'>{r['change']}</td>"
        f"<td style='text-align:right;'>{r['change_percent']}</td>"
        f"</tr>" for r in rows
    )
    data_label = data_timestamp or "N/A"
    return f"""
    <html>
      <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;\">
        <h2 style=\"margin-bottom:4px;\">{REPORT_TITLE}</h2>
        <p style=\"margin:0;color:#666;\">寄送時間：{sent_at} (Asia/Taipei)</p>
        <p style=\"margin:4px 0 12px;color:#94a3b8;\">資料截取：{data_label}</p>
        <div style=\"background:#f5f7fa;border-radius:10px;padding:12px 16px;margin-bottom:12px;line-height:1.6;\">
          <p style=\"margin:0;\">{summary}</p>
          <p style=\"margin:6px 0 0;\">{suggestion}<br/><span style=\"color:#6b7280;font-size:12px;\">{DISCLAIMER}</span></p>
        </div>
        <table style=\"border-collapse:collapse;width:100%;max-width:640px;\">
          <thead>
            <tr style=\"background:#f5f5f5;text-align:left;\">
              <th style=\"padding:8px;\">標的</th>
              <th style=\"padding:8px;text-align:right;\">成交價</th>
              <th style=\"padding:8px;text-align:right;\">漲跌</th>
              <th style=\"padding:8px;text-align:right;\">漲幅</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
      </body>
    </html>
    """


def build_text(sent_at: str, data_timestamp: str, rows: list[dict], summary: str, suggestion: str) -> str:
    lines = [
        REPORT_TITLE,
        f"寄送時間：{sent_at} (Asia/Taipei)",
        f"資料截取：{data_timestamp or 'N/A'}",
        summary,
        suggestion,
        "",
    ]
    for r in rows:
        lines.append(f"{r['label']} ({r['symbol']}): {r['price']} / {r['change']} / {r['change_percent']}")
    return "\n".join(lines)


def format_timestamp(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    return dt.strftime("%Y-%m-%d %H:%M")


def current_taipei_timestamp() -> str:
    return datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")


def send_email(cfg: EmailConfig, subject: str, text: str, html: str) -> str:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg.sender_name} <{cfg.user}>"
    msg["To"] = cfg.recipient

    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(cfg.user, cfg.password)
        response = server.sendmail(cfg.user, [cfg.recipient], msg.as_string())
    if response:
        raise RuntimeError(f"SMTP reported an issue: {response}")
    return cfg.recipient


def push_line_notification(summary: str, suggestion: str, rows: list[dict]) -> None:
    if not LINE_SCRIPT.exists():
        return
    table = build_line_table(rows)
    message = f"{REPORT_TITLE}\n{summary}\n{suggestion}\n\n{table}"
    cmd = ["python3", str(LINE_SCRIPT), message]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"LINE push failed: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send the US market daily report email.")
    parser.add_argument("--to", help="Override recipient email")
    parser.add_argument("--gmail-user", help="Override Gmail user")
    parser.add_argument("--gmail-app-password", help="Override Gmail app password")
    parser.add_argument("--dry-run", action="store_true", help="Print email content instead of sending")
    parser.add_argument("--no-line", action="store_true", help="Skip LINE notification")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = load_latest()
    updated_at = payload.get("updatedAt", "")
    items = payload.get("items", [])
    rows = build_rows(items)
    summary, suggestion = build_summary(items)
    data_timestamp = format_timestamp(updated_at) if updated_at else ""
    sent_at = current_taipei_timestamp()

    subject = f"{REPORT_TITLE} - {sent_at}"
    text_body = build_text(sent_at, data_timestamp, rows, summary, suggestion)
    html_body = build_html(sent_at, data_timestamp, rows, summary, suggestion)

    if args.dry_run:
        print(subject)
        print(text_body)
        if not args.no_line:
            push_line_notification(summary, suggestion, rows)
        return

    cfg = resolve_email_config(args)
    recipient = send_email(cfg, subject, text_body, html_body)
    print(f"Sent US report to {recipient}")
    if not args.no_line:
        push_line_notification(summary, suggestion, rows)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        raise SystemExit(f"Config error: {exc}")
