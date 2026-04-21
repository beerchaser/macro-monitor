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
    orig = html

    # ── TGA val 셀
    html, n = re.subn(
        r'(<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>)',
        lambda m: f'{m.group(1)}{tga["bal_b"]:,.1f}B{m.group(2)}',
        html, count=1
    )
    print(f"  [패치] TGA val: {n}건 교체")

    # ── TGA verify-note
    html, n = re.subn(
        r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
        f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov',
        html
    )
    print(f"  [패치] TGA verify-note: {n}건 교체")

    # ── TGA threshold
    html, n = re.subn(
        r'\d+/\d+ DTS Closing \$[\d,.]+B\(전일',
        f'{tga["date"]} DTS Closing {tga["val_str"]}(전일',
        html
    )
    print(f"  [패치] TGA threshold: {n}건 교체")

    # ── RRP val 셀
    html, n = re.subn(
        r'(<td class="val val-ok">\$)[\d.]+B(</td>\s*<td class="verify">.*?RRPONTSYD)',
        lambda m: f'{m.group(1)}{rrp["val"]:.2f}B{m.group(2)}',
        html, count=1, flags=re.DOTALL
    )
    print(f"  [패치] RRP val: {n}건 교체")

    # ── RRP verify-note
    html, n = re.subn(
        r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
        f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B',
        html
    )
    print(f"  [패치] RRP verify-note: {n}건 교체")

    # ── DGS10 val 셀
    html, n = re.subn(
        r'(<td class="val val-ok">)([\d.]+%)(</td>\s*<td class="verify">.*?FRED DGS10)',
        lambda m: f'{m.group(1)}{dgs10["val"]:.2f}%{m.group(3)}',
        html, count=1, flags=re.DOTALL
    )
    print(f"  [패치] DGS10 val: {n}건 교체")

    # ── DGS10 verify-note
    html, n = re.subn(
        r'\d+/\d+ 종가 · FRED DGS10',
        f'{dgs10["date"]} 종가 · FRED DGS10',
        html
    )
    print(f"  [패치] DGS10 verify-note: {n}건 교체")

    # ── SOFR val 셀
    html, n = re.subn(
        r'(<td class="val val-ok">)([\d.]+%)(\ / [\d.]+%</td>)',
        lambda m: f'{m.group(1)}{sofr["val"]:.2f}%{m.group(3)}',
        html, count=1
    )
    print(f"  [패치] SOFR val: {n}건 교체")

    # ── SOFR verify-note
    html, n = re.subn(
        r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
        f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인',
        html
    )
    print(f"  [패치] SOFR verify-note: {n}건 교체")

    # ── SOFR Repo Stress verify-note
    html, n = re.subn(
        r'\d+/\d+ SOFR [\d.]+% vs IORB [\d.]+% · 역전 해소',
        f'{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB 3.65% · 역전 해소',
        html
    )
    print(f"  [패치] Repo Stress verify-note: {n}건 교체")

    changed = orig != html
    print(f"  [패치] 전체 변경 여부: {'변경됨' if changed else '변경없음 ← 문제!'}")
    return html


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작")

    tga   = fetch_tga()
    print(f"  TGA   : {tga['val_str']} ({tga['date']})")

    dgs10 = fetch_fred("DGS10")
    print(f"  DGS10 : {dgs10['val']:.2f}% ({dgs10['date']})")

    sofr  = fetch_fred("SOFR")
    print(f"  SOFR  : {sofr['val']:.2f}% ({sofr['date']})")

    rrp   = fetch_fred("RRPONTSYD")
    print(f"  RRP   : {rrp['val']:.3f}B ({rrp['date']})")

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    # 현재 파일에서 패턴 존재 여부 미리 확인
    print("\n  [사전확인] 파일 내 패턴 존재 여부:")
    checks = [
        ("TGA verify-note", r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov'),
        ("RRP verify-note", r'\d+/\d+ · FRED RRPONTSYD [\d.]+B'),
        ("DGS10 verify-note", r'\d+/\d+ 종가 · FRED DGS10'),
        ("SOFR verify-note", r'\d+/\d+ SOFR [\d.]+% · FRED 확인'),
    ]
    for name, pattern in checks:
        found = re.search(pattern, html)
        print(f"    {'✅' if found else '❌'} {name}: {found.group(0) if found else '없음'}")

    print()
    html = patch_html(html, tga, dgs10, sofr, rrp)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
