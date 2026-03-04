#!/usr/bin/env python3
"""Send a concise Taiwan market brief to LINE."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "data" / "latest.json"
UPDATE_SCRIPT = BASE_DIR / "scripts" / "update_report.py"
LINE_SCRIPT = BASE_DIR / "scripts" / "notify_line.py"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")

SYMBOLS = {
    "index": "^TWII",
    "tsmc": "2330.TW",
    "0050": "0050.TW",
    "0052": "0052.TW",
    "009816": "009816.TW",
    "00909": "00909.TW",
    "00919": "00919.TW"
}


def load_payload() -> dict[str, Any]:
    with DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def find_item(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    for item in payload.get("items", []):
        if item.get("symbol") == symbol:
            return item
    raise KeyError(f"Symbol {symbol} not found in latest data")


def format_percent(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}%"


def format_index_line(item: dict[str, Any]) -> str:
    price = item["price"]
    change = item["change"]
    pct = item.get("changePercent", 0.0)
    return f"📉 加權指數：{price:,.0f}（{change:+.0f} / {pct:+.2f}%）"


def format_tsmc_line(item: dict[str, Any]) -> str:
    price = item["price"]
    change = item["change"]
    prev_close = price - change
    points = [pt.get("close") for pt in item.get("trend", []) if isinstance(pt.get("close"), (int, float))]
    if points:
        low = min(points)
        high = max(points)
    else:
        low = high = price
    pct_low = ((low - prev_close) / prev_close) * 100 if prev_close else 0.0
    pct_high = ((high - prev_close) / prev_close) * 100 if prev_close else 0.0
    return (
        f"台積電：約{low:.0f}～{high:.0f}（{pct_low:+.1f}～{pct_high:+.1f}%）"
    )


def format_etf_line(label: str, item: dict[str, Any]) -> str:
    return f"{label}：{item['price']:.2f}（{format_percent(item.get('changePercent', 0.0))}）"


def format_income_line(item_a: dict[str, Any], item_b: dict[str, Any]) -> str:
    note = "相對抗跌" if item_a.get("changePercent", 0.0) >= item_b.get("changePercent", 0.0) else "波動加劇"
    return (
        "00909 / 00919：（高息/價值型）"
        f"約{item_a['price']:.2f} / {item_b['price']:.2f}，"
        f"漲跌約 {format_percent(item_a.get('changePercent', 0.0), 1)} / {format_percent(item_b.get('changePercent', 0.0), 1)}，{note}"
    )


def build_summary(index_item: dict[str, Any]) -> str:
    pct = index_item.get("changePercent", 0.0)
    if pct >= 0.8:
        text = "美股反彈與權值股走揚帶動盤勢偏多；短線可逢低加碼大型ETF。"
    elif pct <= -0.8:
        text = "受美股回檔與地緣風險拖累，盤勢偏弱；建議觀望、守好停損。"
    else:
        text = "盤勢震盪整理、資金輪動快；建議分批佈局並控制部位。"
    return f"💡 簡評：{text}"


def should_skip(today: date) -> bool:
    return today.weekday() >= 5  # Sat/Sun


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Taiwan brief to LINE")
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending to LINE")
    parser.add_argument("--skip-update", action="store_true", help="Do not refresh latest data before sending")
    args = parser.parse_args()

    today = datetime.now(TAIPEI_TZ).date()
    if should_skip(today):
        print("Non-trading day (weekend); skipping send_tw_brief.")
        return

    if not args.skip_update and UPDATE_SCRIPT.exists():
        subprocess.run([sys.executable, str(UPDATE_SCRIPT)], check=True)

    payload = load_payload()
    index_item = find_item(payload, SYMBOLS["index"])
    tsmc_item = find_item(payload, SYMBOLS["tsmc"])
    etf_0050 = find_item(payload, SYMBOLS["0050"])
    etf_0052 = find_item(payload, SYMBOLS["0052"])
    etf_009816 = find_item(payload, SYMBOLS["009816"])
    etf_00909 = find_item(payload, SYMBOLS["00909"])
    etf_00919 = find_item(payload, SYMBOLS["00919"])

    date_str = today.strftime("%Y/%m/%d")
    lines = [
        f"【台股快報 {date_str}】",
        format_index_line(index_item),
        format_tsmc_line(tsmc_item),
        "📊 ETF即時（盤後）",
        format_etf_line("0050 元大台灣50", etf_0050),
        format_etf_line("0052 富邦科技", etf_0052),
        format_etf_line("009816 凱基台灣TOP50", etf_009816),
        format_income_line(etf_00909, etf_00919),
        build_summary(index_item)
    ]

    # keep message tight (<= 9 lines)
    message = "\n".join(lines)
    print(message)

    if args.dry_run:
        return

    subprocess.run([sys.executable, str(LINE_SCRIPT), message], check=True)


if __name__ == "__main__":
    main()
