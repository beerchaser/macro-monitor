#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트 v9
- Actions 업데이트 항목: vbadge-auto (보라색) + "자동확인" 배지
- 수동 검색 항목: vbadge-ok (초록색) + "검색확인" 배지 (기존 유지)
"""

import urllib.request
import urllib.parse
import json
import re
import os
from datetime import datetime

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"

# Actions 자동확인 배지 HTML
AUTO_BADGE = '<span class="vbadge vbadge-auto">자동확인</span>'


def http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def safe_fetch(name, fn):
    try:
        result = fn()
        print(f"  ✅ {name}: {result.get('display', str(result)[:30])}")
        return result
    except Exception as e:
        print(f"  ⚠️  {name}: 실패 ({e}) — 이전 값 유지")
        return None


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


def fetch_auction(term="10-Year", sec_type="Note"):
    url = (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
        "/v1/accounting/od/auctions_query"
        f"?fields=auction_date,security_term,indirect_bidder_accepted,comp_accepted"
        f"&filter=security_type:eq:{sec_type},security_term:eq:{term}"
        "&sort=-auction_date&page[size]=1"
    )
    data = http_get(url)
    rows = data.get("data", [])
    if not rows:
        raise ValueError(f"{term} 경매 없음")
    r = rows[0]
    indirect = float(r["indirect_bidder_accepted"])
    comp = float(r["comp_accepted"])
    ratio = round(indirect / comp * 100, 1) if comp else 0
    dt = datetime.strptime(r["auction_date"], "%Y-%m-%d")
    d = f"{dt.month}/{dt.day}"
    return {"ratio": ratio, "date": d, "display": f"{ratio}% IB ({d})"}


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
            return {"val": val, "date": d, "display": f"{val} ({d})"}
    raise ValueError(f"{series_id} 없음")


def sub(html, pattern, replacement, flags=0, label=""):
    result, n = re.subn(pattern, replacement, html, flags=flags)
    tag = label or pattern[:45]
    if n == 0:
        print(f"    ⚠️  미매칭: {tag}")
    else:
        print(f"    ✅ {n}건: {tag}")
    return result


def set_auto_badge(html, anchor_note):
    """verify-note 텍스트를 anchor로 해당 vbadge를 자동확인으로 교체"""
    pattern = r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|ss|est)">(?:검색확인|구버전|스크린샷|추정)</span>(<span class="verify-note">' + re.escape(anchor_note)
    replacement = f'\\g<1>{AUTO_BADGE}\\g<2>{anchor_note}'
    result, n = re.subn(pattern, html.count(anchor_note) and replacement or replacement, html)
    return result, n


def patch_html(html, data):
    tga     = data.get("tga")
    dgs10   = data.get("dgs10")
    sofr    = data.get("sofr")
    rrp     = data.get("rrp")
    nfp     = data.get("nfp")
    cpi     = data.get("cpi")
    unrate  = data.get("unrate")
    ci      = data.get("ci")
    auction = data.get("auction")

    print("\n  [패치 시작]")

    # ── TGA ──
    if tga:
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>)',
            lambda m: f'{m.group(1)}{tga["bal_b"]:,.1f}B{m.group(2)}',
            re.DOTALL, "TGA val")
        new_note = f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov'
        html = sub(html,
            r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
            new_note, label="TGA note")
        html = sub(html,
            r'\d+/\d+ DTS Closing \$[\d,.]+B\(전일',
            f'{tga["date"]} DTS Closing {tga["val_str"]}(전일', label="TGA threshold")
        # 배지 → 자동확인
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ DTS Closing',
            f'\\g<1>{AUTO_BADGE}\\g<2>{tga["date"]} DTS Closing',
            label="TGA badge")

    # ── RRP ──
    if rrp:
        html = sub(html,
            r'(<td class="val val-ok">\$)[\d.]+B(</td>\s*<td class="verify">.*?RRPONTSYD)',
            lambda m: f'{m.group(1)}{rrp["val"]:.2f}B{m.group(2)}',
            re.DOTALL, "RRP val")
        new_note = f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B'
        html = sub(html,
            r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
            new_note, label="RRP note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ · FRED RRPONTSYD',
            f'\\g<1>{AUTO_BADGE}\\g<2>{rrp["date"]} · FRED RRPONTSYD',
            label="RRP badge")

    # ── DGS10 ──
    if dgs10:
        html = sub(html,
            r'(<td class="val val-ok">)([\d.]+%)(</td>\s*<td class="verify">.*?FRED DGS10)',
            lambda m: f'{m.group(1)}{dgs10["val"]:.2f}%{m.group(3)}',
            re.DOTALL, "DGS10 val")
        html = sub(html,
            r'\d+/\d+ 종가 · FRED DGS10',
            f'{dgs10["date"]} 종가 · FRED DGS10', label="DGS10 note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ 종가 · FRED DGS10',
            f'\\g<1>{AUTO_BADGE}\\g<2>{dgs10["date"]} 종가 · FRED DGS10',
            label="DGS10 badge")

    # ── SOFR ──
    if sofr:
        html = sub(html,
            r'(<td class="val val-ok">)([\d.]+%)(\ / [\d.]+%</td>)',
            lambda m: f'{m.group(1)}{sofr["val"]:.2f}%{m.group(3)}',
            label="SOFR val")
        html = sub(html,
            r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인', label="SOFR note")
        html = sub(html,
            r'\d+/\d+ SOFR [\d.]+% vs IORB [\d.]+% · 역전 해소',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB 3.65% · 역전 해소',
            label="Repo Stress note")
        # SOFR 배지 2개
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ SOFR [\d.]+% · FRED 확인',
            f'\\g<1>{AUTO_BADGE}\\g<2>{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인',
            label="SOFR badge")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ SOFR [\d.]+% vs IORB',
            f'\\g<1>{AUTO_BADGE}\\g<2>{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB',
            label="Repo Stress badge")

    # ── 경매 IB ──
    if auction:
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)[\d.]+% \((?:30Y|10Y)\)(</td>)',
            f'\\g<1>{auction["ratio"]}% (10Y)\\g<2>', label="경매 val")
        html = sub(html,
            r'\d+Y \d+/\d+ 경매 · fiscaldata 확인',
            f'10Y {auction["date"]} 경매 · fiscaldata 확인', label="경매 note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+Y \d+/\d+ 경매 · fiscaldata 확인',
            f'\\g<1>{AUTO_BADGE}\\g<2>10Y {auction["date"]} 경매 · fiscaldata 확인',
            label="경매 badge")

    # ── NFP ──
    if nfp:
        nfp_k = int(nfp["val"])
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">3월: \+)[\d,]+K(</td>)',
            f'\\g<1>{nfp_k:,}K\\g<2>', label="NFP val")
        html = sub(html,
            r'\d+/\d+ 발표 · BLS 3월 \+[\d,]+K',
            f'{nfp["date"]} 발표 · BLS 3월 +{nfp_k:,}K', label="NFP note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ 발표 · BLS 3월',
            f'\\g<1>{AUTO_BADGE}\\g<2>{nfp["date"]} 발표 · BLS 3월',
            label="NFP badge")

    # ── Core CPI 날짜 ──
    if cpi:
        html = sub(html,
            r'\d+/\d+ 발표 · 3월 BLS 헤드라인',
            f'{cpi["date"]} 발표 · 3월 BLS 헤드라인', label="CPI note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ 발표 · 3월 BLS 헤드라인',
            f'\\g<1>{AUTO_BADGE}\\g<2>{cpi["date"]} 발표 · 3월 BLS 헤드라인',
            label="CPI badge")

    # ── 실업률 ──
    if unrate:
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)([\d.]+%)(</td>\s*<td class="verify">.*?3월 BLS)',
            lambda m: f'{m.group(1)}{unrate["val"]:.1f}%{m.group(3)}',
            re.DOTALL, "실업률 val")
        html = sub(html,
            r'3월 BLS · \d+/\d+ 발표',
            f'3월 BLS · {unrate["date"]} 발표', label="실업률 note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)3월 BLS · \d+/\d+ 발표',
            f'\\g<1>{AUTO_BADGE}\\g<2>3월 BLS · {unrate["date"]} 발표',
            label="실업률 badge")

    # ── C&I ──
    if ci:
        old_badge = '<span class="vbadge vbadge-old">구버전</span><span class="verify-note">3월 FRED BUSLOANS · 접근 불가</span>'
        new_badge = f'{AUTO_BADGE}<span class="verify-note">{ci["date"]} · FRED BUSLOANS (자동)</span>'
        if old_badge in html:
            html = html.replace(old_badge, new_badge)
            print(f"    ✅ C&I badge+note 교체")
        else:
            html = sub(html,
                r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|auto)">(?:검색확인|자동확인)</span>'
                r'(<span class="verify-note">)\d+/\d+ · FRED BUSLOANS',
                f'\\g<1>{AUTO_BADGE}\\g<2>{ci["date"]} · FRED BUSLOANS',
                label="C&I badge update")

    return html


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작\n")

    data = {}
    data["tga"]     = safe_fetch("TGA",     fetch_tga)
    data["dgs10"]   = safe_fetch("DGS10",   lambda: fetch_fred("DGS10"))
    data["sofr"]    = safe_fetch("SOFR",    lambda: fetch_fred("SOFR"))
    data["rrp"]     = safe_fetch("RRP",     lambda: fetch_fred("RRPONTSYD"))
    data["nfp"]     = safe_fetch("NFP",     lambda: fetch_fred("PAYEMS"))
    data["cpi"]     = safe_fetch("CoreCPI", lambda: fetch_fred("CPILFESL"))
    data["unrate"]  = safe_fetch("UNRATE",  lambda: fetch_fred("UNRATE"))
    data["ci"]      = safe_fetch("C&I",     lambda: fetch_fred("BUSLOANS"))
    data["auction"] = safe_fetch("경매IB",  fetch_auction)

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    html = patch_html(html, data)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
