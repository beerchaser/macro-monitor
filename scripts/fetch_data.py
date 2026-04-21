#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트 v7
자동화 항목:
  Treasury FiscalData : TGA, 국채 경매 Indirect Bidder
  FRED                : DGS10, SOFR, RRPONTSYD, WRMFNS(MMF),
                        PAYEMS(NFP), CPILFESL(CoreCPI), PCEPILFE(CorePCE),
                        UNRATE, BUSLOANS(C&I), M2SL
"""

import urllib.request
import urllib.parse
import json
import re
import os
from datetime import datetime

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"


# ── 공통 fetch 함수 ──────────────────────────────────────────────
def http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def safe_fetch(name, fn):
    """실패해도 None 반환 — 이전 값 유지"""
    try:
        result = fn()
        print(f"  ✅ {name}: {result.get('display', result)}")
        return result
    except Exception as e:
        print(f"  ⚠️  {name}: 실패 ({e}) — 이전 값 유지")
        return None


# ── TGA ──────────────────────────────────────────────────────────
def fetch_tga():
    data = http_get(
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
        "/v1/accounting/dts/operating_cash_balance"
        "?fields=record_date,account_type,open_today_bal"
        "&sort=-record_date&page[size]=20"
    )
    for row in data.get("data", []):
        if "Closing Balance" in row.get("account_type", ""):
            bal_b = float(row["open_today_bal"]) / 1_000
            dt = datetime.strptime(row["record_date"], "%Y-%m-%d")
            d = f"{dt.month}/{dt.day}"
            return {"bal_b": bal_b, "val_str": f"${bal_b:,.1f}B", "date": d,
                    "display": f"${bal_b:,.1f}B ({d})"}
    raise ValueError("TGA 없음")


# ── 국채 경매 Indirect Bidder ────────────────────────────────────
def fetch_auction(term="10-Year", sec_type="Note"):
    data = http_get(
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
        "/v1/accounting/od/auctions_query"
        f"?fields=auction_date,security_term,indirect_bidder_accepted,comp_accepted,bid_to_cover_ratio"
        f"&filter=security_type:eq:{sec_type},security_term:eq:{term}"
        "&sort=-auction_date&page[size]=1"
    )
    rows = data.get("data", [])
    if not rows:
        raise ValueError(f"{term} 경매 없음")
    r = rows[0]
    indirect = float(r["indirect_bidder_accepted"])
    comp = float(r["comp_accepted"])
    ratio = round(indirect / comp * 100, 1) if comp else 0
    btc = float(r["bid_to_cover_ratio"])
    dt = datetime.strptime(r["auction_date"], "%Y-%m-%d")
    d = f"{dt.month}/{dt.day}"
    return {"ratio": ratio, "btc": btc, "date": d,
            "display": f"{ratio}% IB ({d})"}


# ── FRED 공통 ────────────────────────────────────────────────────
def fetch_fred(series_id):
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY 없음")
    params = urllib.parse.urlencode({
        "series_id": series_id, "api_key": FRED_API_KEY,
        "file_type": "json", "sort_order": "desc", "limit": 5
    })
    data = http_get(f"https://api.stlouisfed.org/fred/series/observations?{params}")
    for obs in data.get("observations", []):
        if obs["value"] != ".":
            val = float(obs["value"])
            dt = datetime.strptime(obs["date"], "%Y-%m-%d")
            d = f"{dt.month}/{dt.day}"
            return {"val": val, "date": d, "raw_date": obs["date"],
                    "display": f"{val} ({d})"}
    raise ValueError(f"{series_id} 없음")


# ── HTML 패치 ────────────────────────────────────────────────────
def sub(html, pattern, replacement, flags=0):
    result, n = re.subn(pattern, replacement, html, flags=flags)
    if n == 0:
        print(f"    ⚠️  패턴 미매칭: {pattern[:60]}")
    return result, n


def patch_html(html, data):
    tga    = data.get("tga")
    dgs10  = data.get("dgs10")
    sofr   = data.get("sofr")
    rrp    = data.get("rrp")
    mmf    = data.get("mmf")
    nfp    = data.get("nfp")
    cpi    = data.get("cpi")
    pce    = data.get("pce")
    unrate = data.get("unrate")
    ci     = data.get("ci")
    m2     = data.get("m2")
    auction= data.get("auction")

    print("\n  [패치 시작]")

    # ── TGA ──
    if tga:
        html, _ = sub(html,
            r'(<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>)',
            lambda m: f'{m.group(1)}{tga["bal_b"]:,.1f}B{m.group(2)}',
            re.DOTALL)
        html, _ = sub(html,
            r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
            f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov')
        html, _ = sub(html,
            r'\d+/\d+ DTS Closing \$[\d,.]+B\(전일',
            f'{tga["date"]} DTS Closing {tga["val_str"]}(전일')

    # ── RRP ──
    if rrp:
        html, _ = sub(html,
            r'(<td class="val val-ok">\$)[\d.]+B(</td>\s*<td class="verify">.*?RRPONTSYD)',
            lambda m: f'{m.group(1)}{rrp["val"]:.2f}B{m.group(2)}',
            re.DOTALL)
        html, _ = sub(html,
            r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
            f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B')

    # ── DGS10 ──
    if dgs10:
        html, _ = sub(html,
            r'(<td class="val val-ok">)([\d.]+%)(</td>\s*<td class="verify">.*?FRED DGS10)',
            lambda m: f'{m.group(1)}{dgs10["val"]:.2f}%{m.group(3)}',
            re.DOTALL)
        html, _ = sub(html,
            r'\d+/\d+ 종가 · FRED DGS10',
            f'{dgs10["date"]} 종가 · FRED DGS10')

    # ── SOFR ──
    if sofr:
        html, _ = sub(html,
            r'(<td class="val val-ok">)([\d.]+%)(\ / [\d.]+%</td>)',
            lambda m: f'{m.group(1)}{sofr["val"]:.2f}%{m.group(3)}')
        html, _ = sub(html,
            r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인')
        html, _ = sub(html,
            r'\d+/\d+ SOFR [\d.]+% vs IORB [\d.]+% · 역전 해소',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB 3.65% · 역전 해소')

    # ── MMF AUM ──
    if mmf:
        mmf_t = mmf["val"] / 1_000  # B → T
        html, _ = sub(html,
            r'(<td class="val val-(?:ok|warn)">\$)[\d.]+조(</td>\s*<td class="verify">.*?ICI)',
            lambda m: f'{m.group(1)}{mmf_t:.2f}조{m.group(2)}',
            re.DOTALL)
        html, _ = sub(html,
            r'\d+/\d+ ICI 주간치 · 검색 확인',
            f'{mmf["date"]} ICI 주간치 · FRED WRMFNS')

    # ── 국채 경매 Indirect Bidder ──
    if auction:
        html, _ = sub(html,
            r'(<td class="val val-(?:ok|warn)">)[\d.]+%\s*\((?:30Y|10Y)[^)]*\)(</td>\s*<td class="verify">.*?fiscaldata)',
            lambda m: f'{m.group(1)}{auction["ratio"]}% (10Y){m.group(2)}',
            re.DOTALL)
        html, _ = sub(html,
            r'\d+Y \d+/\d+ 경매 · fiscaldata 확인',
            f'10Y {auction["date"]} 경매 · fiscaldata 확인')

    # ── NFP ──
    if nfp:
        nfp_k = int(nfp["val"])
        html, _ = sub(html,
            r'(<td class="val val-(?:ok|warn)">3월: \+)[\d,]+K(</td>)',
            lambda m: f'{m.group(1)}{nfp_k:,}K{m.group(2)}')
        html, _ = sub(html,
            r'\d+/\d+ 발표 · BLS 3월 \+[\d,]+K',
            f'{nfp["date"]} 발표 · BLS 3월 +{nfp_k:,}K')

    # ── Core CPI / Core PCE ──
    if cpi and pce:
        # CPI YoY는 인덱스값이라 별도 계산 필요 — verify-note 날짜만 업데이트
        html, _ = sub(html,
            r'\d+/\d+ 발표 · 3월 BLS 헤드라인',
            f'{cpi["date"]} 발표 · 3월 BLS 헤드라인')

    # ── 실업률 ──
    if unrate:
        html, _ = sub(html,
            r'(<td class="val val-(?:ok|warn)">)([\d.]+%)(</td>\s*<td class="verify">.*?BLS)',
            lambda m: f'{m.group(1)}{unrate["val"]:.1f}%{m.group(3)}',
            re.DOTALL)
        html, _ = sub(html,
            r'3월 BLS · \d+/\d+ 발표',
            f'3월 BLS · {unrate["date"]} 발표')

    # ── H.8 C&I 대출 ──
    if ci:
        html, _ = sub(html,
            r'(<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>\s*<td class="verify">.*?BUSLOANS)',
            lambda m: f'{m.group(1)}{ci["val"]:,.1f}B{m.group(2)}',
            re.DOTALL)
        html, _ = sub(html,
            r'3월 FRED BUSLOANS · 접근 불가',
            f'{ci["date"]} · FRED BUSLOANS')
        # vbadge 구버전 → 검색확인
        html = html.replace(
            '<span class="vbadge vbadge-old">구버전</span><span class="verify-note">3월 FRED BUSLOANS · 접근 불가</span>',
            f'<span class="vbadge vbadge-ok">검색확인</span><span class="verify-note">{ci["date"]} · FRED BUSLOANS</span>'
        )

    # ── M2 ──
    if m2:
        m2_t = m2["val"] / 1_000  # B → T
        html, _ = sub(html,
            r'(<td class="val val-(?:ok|warn)">[\d.]+)(</td>\s*<td class="verify">.*?분기 데이터)',
            lambda m: f'{m.group(1).rsplit(">",1)[0]}>{m2_t:.3f}{m.group(2)}',
            re.DOTALL)

    return html


# ── Main ─────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작\n")

    data = {}
    data["tga"]     = safe_fetch("TGA",      fetch_tga)
    data["dgs10"]   = safe_fetch("DGS10",    lambda: fetch_fred("DGS10"))
    data["sofr"]    = safe_fetch("SOFR",     lambda: fetch_fred("SOFR"))
    data["rrp"]     = safe_fetch("RRP",      lambda: fetch_fred("RRPONTSYD"))
    data["mmf"]     = safe_fetch("MMF",      lambda: fetch_fred("WRMFNS"))
    data["nfp"]     = safe_fetch("NFP",      lambda: fetch_fred("PAYEMS"))
    data["cpi"]     = safe_fetch("CoreCPI",  lambda: fetch_fred("CPILFESL"))
    data["pce"]     = safe_fetch("CorePCE",  lambda: fetch_fred("PCEPILFE"))
    data["unrate"]  = safe_fetch("UNRATE",   lambda: fetch_fred("UNRATE"))
    data["ci"]      = safe_fetch("C&I",      lambda: fetch_fred("BUSLOANS"))
    data["m2"]      = safe_fetch("M2",       lambda: fetch_fred("M2SL"))
    data["auction"] = safe_fetch("경매IB",    fetch_auction)

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    html = patch_html(html, data)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
