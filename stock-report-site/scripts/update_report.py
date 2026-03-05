#!/usr/bin/env python3
import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

TZ = ZoneInfo("Asia/Taipei")

# NOTE:
# Please verify ticker for 「凱基台灣TOP50」 if you use a different fund code.
ASSETS = [
    {"label": "加權指數", "symbol": "^TWII", "type": "Index"},
    {"label": "台積電", "symbol": "2330.TW", "type": "Stock"},
    {"label": "富邦科技", "symbol": "0052.TW", "type": "ETF"},
    {"label": "元大台灣50", "symbol": "0050.TW", "type": "ETF"},
    {"label": "凱基台灣TOP50", "symbol": "009816.TW", "type": "ETF"},
    {"label": "群益台灣精選高息", "symbol": "00919.TW", "type": "ETF"},
    {"label": "國泰數位支付服務", "symbol": "00909.TW", "type": "ETF"},
]


def fmt(value, digits=2):
    if value is None:
        return None
    return round(float(value), digits)


def is_trading_window(now: datetime) -> bool:
    if now.weekday() >= 5:  # Sat/Sun
        return False
    market_open = time(9, 0)
    market_close = time(13, 30)
    return market_open <= now.time() <= market_close


def fetch_quote(symbol: str):
    ticker = yf.Ticker(symbol)

    # 15-minute intraday for latest price in current session
    intraday = ticker.history(period="1d", interval="15m", auto_adjust=False)

    latest = None
    if not intraday.empty and "Close" in intraday:
        closes = intraday["Close"].dropna()
        if not closes.empty:
            latest = closes.iloc[-1]

    # Use recent daily close as reference for change/%
    daily = ticker.history(period="5d", interval="1d", auto_adjust=False)
    previous = None
    if not daily.empty and "Close" in daily:
        dclose = daily["Close"].dropna()
        if len(dclose) >= 2:
            previous = dclose.iloc[-2]
        elif len(dclose) == 1:
            previous = dclose.iloc[-1]

    change = (latest - previous) if (latest is not None and previous is not None) else None
    change_pct = ((change / previous) * 100) if (change is not None and previous not in (None, 0)) else None

    currency = None
    try:
        finfo = ticker.fast_info or {}
        if isinstance(finfo, dict):
            currency = finfo.get("currency")
    except Exception:
        pass

    trend_points = []
    if not intraday.empty and "Close" in intraday:
        trend_series = intraday["Close"].dropna().tail(20)
        for idx, val in trend_series.items():
            trend_points.append(
                {
                    "time": idx.tz_convert(TZ).strftime("%H:%M") if getattr(idx, "tzinfo", None) else idx.strftime("%H:%M"),
                    "close": fmt(val, 2),
                }
            )

    return {
        "price": fmt(latest, 2),
        "change": fmt(change, 2),
        "changePercent": fmt(change_pct, 2),
        "currency": currency or "TWD",
        "trend": trend_points,
    }


def build_report(now: datetime):
    items = []
    for asset in ASSETS:
        quote = fetch_quote(asset["symbol"])
        items.append(
            {
                "label": asset["label"],
                "symbol": asset["symbol"],
                "type": asset["type"],
                **quote,
            }
        )

    return {
        "updatedAt": now.isoformat(),
        "timezone": "Asia/Taipei",
        "source": {
            "name": "Yahoo Finance",
            "provider": "yfinance",
            "url": "https://finance.yahoo.com/"
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
