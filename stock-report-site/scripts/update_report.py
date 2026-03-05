#!/usr/bin/env python3
import json
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TZ = ZoneInfo("Asia/Taipei")
MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Referer": "https://mis.twse.com.tw/stock/index.jsp",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

ASSETS = [
    {"label": "加權指數", "symbol": "^TWII", "type": "Index", "channel": "tse_t00.tw"},
    {"label": "台積電", "symbol": "2330.TW", "type": "Stock", "channel": "tse_2330.tw"},
    {"label": "富邦科技", "symbol": "0052.TW", "type": "ETF", "channel": "tse_0052.tw"},
    {"label": "元大台灣50", "symbol": "0050.TW", "type": "ETF", "channel": "tse_0050.tw"},
    {"label": "凱基台灣TOP50", "symbol": "009816.TW", "type": "ETF", "channel": "tse_009816.tw"},
    {"label": "群益台灣精選高息", "symbol": "00919.TW", "type": "ETF", "channel": "tse_00919.tw"},
    {"label": "國泰數位支付服務", "symbol": "00909.TW", "type": "ETF", "channel": "tse_00909.tw"},
]


def parse_decimal(value) -> Decimal | None:
    if value in (None, "", "-", "+"):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def fmt(dec: Decimal | None, digits: int = 2) -> float | None:
    if dec is None:
        return None
    quant = Decimal(10) ** -digits
    return float(dec.quantize(quant))


def parse_timestamp(date_str: str | None, time_str: str | None) -> datetime | None:
    if not date_str or not time_str:
        return None
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M:%S")
        return dt.replace(tzinfo=TZ)
    except ValueError:
        return None


def is_trading_window(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    market_open = time(9, 0)
    market_close = time(13, 30)
    return market_open <= now.time() <= market_close


def fetch_mis_quotes(channels: List[str]) -> Dict[str, dict]:
    params = {"ex_ch": "|".join(channels), "json": 1}
    response = requests.get(MIS_URL, params=params, headers=MIS_HEADERS, timeout=10, verify=False)
    response.raise_for_status()
    payload = response.json()
    quotes = {}
    for entry in payload.get("msgArray", []):
        channel = entry.get("ch")
        if channel:
            quotes[channel] = entry
    return quotes


def build_quote(entry: dict | None) -> dict:
    if not entry:
        return {"price": None, "change": None, "changePercent": None, "currency": "TWD", "trend": []}

    last = parse_decimal(entry.get("z"))
    prev_close = parse_decimal(entry.get("y"))
    price = fmt(last)
    change = None
    change_pct = None

    if last is not None and prev_close is not None:
        delta = last - prev_close
        change = fmt(delta)
        if prev_close != 0:
            change_pct = fmt((delta / prev_close) * 100)

    timestamp = parse_timestamp(entry.get("d"), entry.get("t"))
    time_label = timestamp.strftime("%H:%M") if timestamp else None
    trend = []
    if prev_close is not None:
        trend.append({"time": "前收", "close": fmt(prev_close)})
    if price is not None and time_label:
        trend.append({"time": time_label, "close": price})

    return {
        "price": price,
        "change": change,
        "changePercent": change_pct,
        "currency": "TWD",
        "trend": trend,
        "timestamp": timestamp.isoformat() if timestamp else None,
    }


def build_report(now: datetime):
    channels = [asset["channel"] for asset in ASSETS]
    raw_quotes = fetch_mis_quotes(channels)

    items = []
    data_date = None
    for asset in ASSETS:
        channel_key = asset["channel"].split("_", 1)[-1]
        entry = raw_quotes.get(channel_key)
        quote = build_quote(entry)

        if not data_date and entry:
            data_date = entry.get("d")

        items.append({
            "label": asset["label"],
            "symbol": asset["symbol"],
            "type": asset["type"],
            "price": quote["price"],
            "change": quote["change"],
            "changePercent": quote["changePercent"],
            "currency": quote["currency"],
            "trend": quote["trend"],
            "timestamp": quote["timestamp"],
        })

    data_date_iso = None
    if data_date:
        try:
            data_date_iso = datetime.strptime(data_date, "%Y%m%d").date().isoformat()
        except ValueError:
            data_date_iso = None

    return {
        "updatedAt": now.isoformat(),
        "timezone": "Asia/Taipei",
        "dataDate": data_date_iso,
        "source": {
            "name": "臺灣證券交易所 MIS",
            "provider": "TWSE",
            "url": "https://mis.twse.com.tw/stock/index.jsp",
            "remarks": "官方撮合即時資料（約 5 秒延遲）",
        },
        "market": {
            "name": "TWSE",
            "open": "09:00",
            "close": "13:30",
            "isTradingWindow": is_trading_window(now),
        },
        "items": items,
    }


def main():
    now = datetime.now(tz=TZ)
    report = build_report(now)

    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_file = data_dir / "latest.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Updated {out_file} at {now.isoformat()}")


if __name__ == "__main__":
    main()
