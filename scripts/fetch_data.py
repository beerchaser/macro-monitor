#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트
- Treasury FiscalData API : TGA 잔고 (키 불필요)
- FRED API                : DGS10, SOFR, RRPONTSYD (FRED_API_KEY 환경변수)
"""

import urllib.request
import urllib.parse
import json
import re
import os
from datetime import datetime

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"


def fetch_tga():
    url = (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
        "/v1/accounting/dts/operating_cash_balance"
        "?fields=record_date,account_type,open_today_bal"
        "&sort=-record_date"
        "&page[size]=20"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    for row in data.get("data", []):
        if "Closing Balance" in row.get("account_type", ""):
            bal_b = float(row["open_today_bal"]) / 1_000
            dt = datetime.strptime(row["record_date"], "%Y-%m-%d")
            date_str = f"{dt.month}/{dt.day}"
            return {
                "val_str": f"${bal_b:,.0f}B",
                "date": date_str,
                "note": f"{date_str} · Treasury FiscalData DTS"
            }
    raise ValueError("TGA Closing Balance 행 없음")


def fetch_fred(series_id):
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY 환경변수 없음")
    params = urllib.parse.urlencode({
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5
    })
    url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    for obs in data.get("observations", []):
        if obs["value"] != ".":
            val = float(obs["value"])
            dt = datetime.strptime(obs["date"], "%Y-%m-%d")
            date_str = f"{dt.month}/{dt.day}"
            return {"val": val, "date": date_str}
    raise ValueError(f"{series_id} 유효값 없음")


def patch_html(html, tga, dgs10, sofr, rrp):
    subs = [
        (r'\d+/\d+ · Treasury FiscalData DTS',
         tga["note"]),
        (r'\d+/\d+ 종가 · FRED DGS10',
         f'{dgs10["date"]} 종가 · FRED DGS10'),
        (r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
         f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인'),
        (r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
         f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B'),
        (r'(?<=<td class="val val-ok">)\d+\.\d+(?=%</td>)',
         f'{dgs10["val"]:.2f}'),
        (r'(?<=<td class="val val-ok">)\d+\.\d+(?=% / \d+\.\d+%</td>)',
         f'{sofr["val"]:.2f}'),
        (r'(?<=<td class="val val-ok">\$)\d+\.\d+(?=B</td>)',
         f'{rrp["val"]:.2f}'),
    ]
    for pattern, replacement in subs:
        html = re.sub(pattern, replacement, html)
    return html


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작")

    tga = fetch_tga()
    print(f"  TGA   : {tga['val_str']} ({tga['date']})")

    dgs10 = fetch_fred("DGS10")
    print(f"  DGS10 : {dgs10['val']:.2f}% ({dgs10['date']})")

    sofr = fetch_fred("SOFR")
    print(f"  SOFR  : {sofr['val']:.2f}% ({sofr['date']})")

    rrp = fetch_fred("RRPONTSYD")
    print(f"  RRP   : {rrp['val']:.3f}B ({rrp['date']})")

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    html = patch_html(html, tga, dgs10, sofr, rrp)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
