#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트
- Treasury FiscalData API: TGA 잔고 (키 불필요)
- FRED API: DGS10, SOFR, RRPONTSYD (키 필요)
"""

import urllib.request
import urllib.parse
import json
import re
import os
import sys
from datetime import datetime

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"

# ─────────────────────────────────────────
# 1) Treasury FiscalData — TGA 잔고
# ─────────────────────────────────────────
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

    rows = data.get("data", [])
    # "Treasury General Account (TGA) Closing Balance" 행 찾기
    for row in rows:
        if "Closing Balance" in row.get("account_type", ""):
            bal_m = float(row["open_today_bal"])
            bal_b = bal_m / 1_000
            dt = datetime.strptime(row["record_date"], "%Y-%m-%d")
            date_str = f"{dt.month}/{dt.day}"
            return {
                "val": f"${bal_b:,.0f}B",
                "date": date_str,
                "raw_date": row["record_date"],
                "note": f"{date_str} · Treasury FiscalData DTS"
            }
    raise ValueError("TGA Closing Balance 행 없음")

# ─────────────────────────────────────────
# 2) FRED API — DGS10 / SOFR / RRPONTSYD
# ─────────────────────────────────────────
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
            return {
                "val": val,
                "date": date_str,
                "raw_date": obs["date"],
                "note": f"{date_str} · FRED {series_id}"
            }
    raise ValueError(f"{series_id} 유효값 없음")

# ─────────────────────────────────────────
# 3) HTML 업데이트 — 정규식 패턴 매칭
# ─────────────────────────────────────────
def fmt_pct(val):
    return f"{val:.2f}%"

def status_class(series_id, val):
    """값에 따른 CSS 클래스 결정"""
    if series_id == "DGS10":
        return "val-warn" if val >= 4.5 else "val-ok"
    if series_id == "RRPONTSYD":
        return "val-warn" if val < 0.5 else "val-ok"
    return "val-ok"

def update_tga(html, tga):
    """TGA 잔고 셀 업데이트"""
    # val 셀
    html = re.sub(
        r'(<td class="val[^"]*">\$)[\d,]+(B</td>\s*'
        r'<td class="verify"><span class="vbadge[^"]*">[^<]*</span>'
        r'<span class="verify-note">[^<]*Treasury)',
        lambda m: m.group(0)[:m.group(0).index('>')+1]
                  .replace(m.group(0)[:m.group(0).index('>')+1],
                           f'<td class="val val-ok">{tga["val"]}</td>\n'
                           f'  <td class="verify">'
                           f'<span class="vbadge vbadge-ok">검색확인</span>'
                           f'<span class="verify-note">{tga["note"]} Treasury'),
        html, count=1
    )
    return html

def update_fred_cell(html, series_id, result):
    """FRED 시리즈별 셀 업데이트 — verify-note 날짜/출처 갱신"""
    note_pattern = rf'(FRED {series_id}[^<]*</span>)'
    new_note = f'FRED {series_id}</span>'

    # verify-note 업데이트
    html = re.sub(
        rf'(<span class="verify-note">[^<]*?){re.escape(result["raw_date"][:7])}[^<]*(</span>)',
        lambda m: m.group(0),  # 패턴 확인용 — 아래에서 직접 처리
        html, count=0
    )
    return html

def patch_html(html, tga, dgs10, sofr, rrp):
    """
    verify-note 안의 날짜+출처 텍스트를 직접 치환
    패턴: "M/D · FRED SERIES_ID" or "M/D · Treasury..."
    """
    # TGA
    html = re.sub(
        r'(\d+/\d+) · Treasury FiscalData DTS',
        tga["note"],
        html
    )

    # DGS10
    old_dgs10_note_pat = r'\d+/\d+ (?:종가 ·|· )FRED DGS10'
    html = re.sub(old_dgs10_note_pat, dgs10["note"], html)
    # val 셀 DGS10
    html = re.sub(
        r'(<td class="val val-[^"]*">)([\d.]+%)(</td>\s*<td class="verify"><span[^>]*>[^<]*</span><span class="verify-note">' + re.escape(dgs10["note"])),
        lambda m: f'<td class="val {status_class("DGS10", dgs10["val"])}">{fmt_pct(dgs10["val"])}</td>'
                  + m.group(0)[m.group(0).index('</td>')+5:],
        html, count=1
    )

    # SOFR
    old_sofr_note_pat = r'\d+/\d+ SOFR [\d.]+% · FRED 확인'
    html = re.sub(old_sofr_note_pat, f'{sofr["date"]} SOFR {fmt_pct(sofr["val"])} · FRED 확인', html)

    # RRP
    old_rrp_note_pat = r'\d+/\d+ · FRED RRPONTSYD[\d.]+B'
    html = re.sub(old_rrp_note_pat, rrp["note"], html)

    return html

# ─────────────────────────────────────────
# 4) 심플 패치 — verify-note 날짜만 교체
# ─────────────────────────────────────────
def simple_patch(html, tga, dgs10, sofr, rrp):
    """
    verify-note 텍스트를 키워드 기반으로 교체.
    HTML 구조가 바뀌어도 안전하게 동작.
    """
    replacements = [
        # TGA
        (r'\d+/\d+ · Treasury FiscalData DTS',
         tga["note"]),
        # DGS10 verify-note
        (r'\d+/\d+ 종가 · FRED DGS10',
         f'{dgs10["date"]} 종가 · FRED DGS10'),
        # SOFR verify-note
        (r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
         f'{sofr["date"]} SOFR {fmt_pct(sofr["val"])} · FRED 확인'),
        # RRP verify-note
        (r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
         f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B'),
        # DGS10 val 셀 (숫자값)
        (r'(?<=<td class="val val-ok">)\d+\.\d+%(?=</td>\s*<td class="verify">[^<]*FRED DGS10)',
         fmt_pct(dgs10["val"])),
        # SOFR val 셀
        (r'(?<=<td class="val val-ok">)[\d.]+% / [\d.]+%(?=</td>)',
         f'{fmt_pct(sofr["val"])} / 3.65%'),
        # RRP val 셀
        (r'(?<=<td class="val val-ok">\$)[\d.]+(?=B</td>\s*<td class="verify">[^<]*RRPONTSYD)',
         f'{rrp["val"]:.2f}'),
    ]

    for pattern, replacement in replacements:
        html = re.sub(pattern, replacement, html)

    return html

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작")

    # 1. 데이터 조회
    print("  TGA 조회 중...")
    tga = fetch_tga()
    print(f"  → TGA {tga['val']} ({tga['date']})")

    print("  FRED DGS10 조회 중...")
    dgs10 = fetch_fred("DGS10")
    print(f"  → DGS10 {fmt_pct(dgs10['val'])} ({dgs10['date']})")

    print("  FRED SOFR 조회 중...")
    sofr = fetch_fred("SOFR")
    print(f"  → SOFR {fmt_pct(sofr['val'])} ({sofr['date']})")

    print("  FRED RRPONTSYD 조회 중...")
    rrp = fetch_fred("RRPONTSYD")
    print(f"  → RRP {rrp['val']:.3f}B ({rrp['date']})")

    # 2. HTML 읽기
    print(f"\n  HTML 읽기: {MONITOR_FILE}")
    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    # 3. 패치
    print("  HTML 업데이트 중...")
    html = simple_patch(html, tga, dgs10, sofr, rrp)

    # 4. 저장
    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n완료: {MONITOR_FILE} 업데이트됨")
    print(f"  TGA:   {tga['val']} ({tga['date']})")
    print(f"  DGS10: {fmt_pct(dgs10['val'])} ({dgs10['date']})")
    print(f"  SOFR:  {fmt_pct(sofr['val'])} ({sofr['date']})")
    print(f"  RRP:   {rrp['val']:.3f}B ({rrp['date']})")

if __name__ == "__main__":
    main()
