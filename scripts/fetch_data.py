#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트
실제 monitor.html 패턴 기반으로 정확히 교체
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
            month_day = f"{dt.month}/{dt.day}"
            return {
                "val_str": f"${bal_b:,.1f}B",
                "bal_b": bal_b,
                "date": month_day,
                "raw_date": row["record_date"],
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
            return {
                "val": val,
                "date": f"{dt.month}/{dt.day}",
                "raw_date": obs["date"],
            }
    raise ValueError(f"{series_id} 유효값 없음")


def patch_html(html, tga, dgs10, sofr, rrp):
    # ── TGA val 셀: $971.1B 형태
    html = re.sub(
        r'(<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>)',
        lambda m: f'{m.group(1)}{tga["bal_b"]:,.1f}B{m.group(2)}',
        html, count=1
    )
    # ── TGA verify-note: "4/16 DTS Closing $971.1B · fiscaldata.treasury.gov"
    html = re.sub(
        r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
        f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov',
        html
    )
    # ── TGA threshold 텍스트 안의 날짜+금액
    html = re.sub(
        r'4/\d+ DTS Closing \$[\d,.]+B\(전일',
        f'{tga["date"]} DTS Closing {tga["val_str"]}(전일',
        html
    )

    # ── RRP val 셀: $0.50B 형태
    html = re.sub(
        r'(<td class="val val-ok">\$)[\d.]+B(</td>\s*<td class="verify">.*?RRPONTSYD)',
        lambda m: f'{m.group(1)}{rrp["val"]:.2f}B{m.group(2)}',
        html, count=1, flags=re.DOTALL
    )
    # ── RRP verify-note: "4/20 · FRED RRPONTSYD 0.503B"
    html = re.sub(
        r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
        f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B',
        html
    )

    # ── DGS10 val 셀: "4.26%" 형태 (verify-note 바로 앞)
    html = re.sub(
        r'(<td class="val val-ok">)([\d.]+%)(</td>\s*<td class="verify">.*?FRED DGS10)',
        lambda m: f'{m.group(1)}{dgs10["val"]:.2f}%{m.group(3)}',
        html, count=1, flags=re.DOTALL
    )
    # ── DGS10 verify-note: "4/17 종가 · FRED DGS10"
    html = re.sub(
        r'\d+/\d+ 종가 · FRED DGS10',
        f'{dgs10["date"]} 종가 · FRED DGS10',
        html
    )

    # ── SOFR val 셀: "3.65% / 3.65%" 형태
    html = re.sub(
        r'(<td class="val val-ok">)([\d.]+%)(\ / [\d.]+%</td>)',
        lambda m: f'{m.group(1)}{sofr["val"]:.2f}%{m.group(3)}',
        html, count=1
    )
    # ── SOFR verify-note (두 군데): "4/17 SOFR 3.65% · FRED 확인"
    html = re.sub(
        r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
        f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인',
        html
    )
    # ── SOFR Repo Stress verify-note: "4/17 SOFR 3.65% vs IORB 3.65% · 역전 해소"
    html = re.sub(
        r'\d+/\d+ SOFR [\d.]+% vs IORB [\d.]+% · 역전 해소',
        f'{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB 3.65% · 역전 해소',
        html
    )

    return html


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작")

    tga  = fetch_tga()
    print(f"  TGA   : {tga['val_str']} ({tga['date']})")

    dgs10 = fetch_fred("DGS10")
    print(f"  DGS10 : {dgs10['val']:.2f}% ({dgs10['date']})")

    sofr  = fetch_fred("SOFR")
    print(f"  SOFR  : {sofr['val']:.2f}% ({sofr['date']})")

    rrp   = fetch_fred("RRPONTSYD")
    print(f"  RRP   : {rrp['val']:.3f}B ({rrp['date']})")

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    html = patch_html(html, tga, dgs10, sofr, rrp)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
