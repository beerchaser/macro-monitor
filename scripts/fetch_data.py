#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트
- TGA     : Treasury FiscalData API (키 불필요)
- DGS10   : FRED API
- SOFR    : FRED API (실패 시 스킵 — 이전 값 유지)
- RRP     : FRED API
"""

import urllib.request
import urllib.parse
import json
import re
import os
from datetime import datetime

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"


# ── TGA : Treasury FiscalData ────────────────────────────────────
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
            return {
                "val_str": f"${bal_b:,.1f}B",
                "bal_b": bal_b,
                "date": f"{dt.month}/{dt.day}",
            }
    raise ValueError("TGA Closing Balance 행 없음")


# ── FRED API ─────────────────────────────────────────────────────
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
            return {
                "val": val,
                "date": f"{dt.month}/{dt.day}",
            }
    raise ValueError(f"{series_id} 유효값 없음")


# ── HTML 패치 ────────────────────────────────────────────────────
def patch_html(html, tga, dgs10, sofr, rrp):

    # TGA val 셀
    html, n = re.subn(
        r'(<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>)',
        lambda m: f'{m.group(1)}{tga["bal_b"]:,.1f}B{m.group(2)}',
        html, count=1
    )
    print(f"  [패치] TGA val: {n}건")

    # TGA verify-note
    html, n = re.subn(
        r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
        f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov',
        html
    )
    print(f"  [패치] TGA note: {n}건")

    # TGA threshold 텍스트
    html, n = re.subn(
        r'\d+/\d+ DTS Closing \$[\d,.]+B\(전일',
        f'{tga["date"]} DTS Closing {tga["val_str"]}(전일',
        html
    )
    print(f"  [패치] TGA threshold: {n}건")

    # RRP val 셀
    html, n = re.subn(
        r'(<td class="val val-ok">\$)[\d.]+B(</td>\s*<td class="verify">.*?RRPONTSYD)',
        lambda m: f'{m.group(1)}{rrp["val"]:.2f}B{m.group(2)}',
        html, count=1, flags=re.DOTALL
    )
    print(f"  [패치] RRP val: {n}건")

    # RRP verify-note
    html, n = re.subn(
        r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
        f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B',
        html
    )
    print(f"  [패치] RRP note: {n}건")

    # DGS10 val 셀
    html, n = re.subn(
        r'(<td class="val val-ok">)([\d.]+%)(</td>\s*<td class="verify">.*?FRED DGS10)',
        lambda m: f'{m.group(1)}{dgs10["val"]:.2f}%{m.group(3)}',
        html, count=1, flags=re.DOTALL
    )
    print(f"  [패치] DGS10 val: {n}건")

    # DGS10 verify-note
    html, n = re.subn(
        r'\d+/\d+ 종가 · FRED DGS10',
        f'{dgs10["date"]} 종가 · FRED DGS10',
        html
    )
    print(f"  [패치] DGS10 note: {n}건")

    # SOFR — 데이터 있을 때만 패치
    if sofr:
        html, n = re.subn(
            r'(<td class="val val-ok">)([\d.]+%)(\ / [\d.]+%</td>)',
            lambda m: f'{m.group(1)}{sofr["val"]:.2f}%{m.group(3)}',
            html, count=1
        )
        print(f"  [패치] SOFR val: {n}건")

        html, n = re.subn(
            r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인',
            html
        )
        print(f"  [패치] SOFR note: {n}건")

        html, n = re.subn(
            r'\d+/\d+ SOFR [\d.]+% vs IORB [\d.]+% · 역전 해소',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB 3.65% · 역전 해소',
            html
        )
        print(f"  [패치] Repo Stress note: {n}건")
    else:
        print("  [패치] SOFR: 스킵 (데이터 없음 — 이전 값 유지)")

    return html


# ── Main ─────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작")

    tga = fetch_tga()
    print(f"  TGA   : {tga['val_str']} ({tga['date']})")

    dgs10 = fetch_fred("DGS10")
    print(f"  DGS10 : {dgs10['val']:.2f}% ({dgs10['date']})")

    # SOFR — 실패 시 None으로 처리 (이전 값 유지)
    try:
        sofr = fetch_fred("SOFR")
        print(f"  SOFR  : {sofr['val']:.2f}% ({sofr['date']})")
    except Exception as e:
        sofr = None
        print(f"  SOFR  : 조회 실패 ({e}) — 이전 값 유지")

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
