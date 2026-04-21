#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트 v8
수정: MMF 제거(ICI 전체 시리즈 FRED 없음), C&I 패턴 충돌 수정
"""

import urllib.request
import urllib.parse
import json
import re
import os
from datetime import datetime

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"


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
        f"?fields=auction_date,security_term,indirect_bidder_accepted,comp_accepted,bid_to_cover_ratio"
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


def sub(html, pattern, replacement, flags=0):
    result, n = re.subn(pattern, replacement, html, flags=flags)
    if n == 0:
        print(f"    ⚠️  미매칭: {pattern[:50]}")
    else:
        print(f"    ✅ {n}건: {pattern[:50]}")
    return result


def patch_html(html, data):
    tga     = data.get("tga")
    dgs10   = data.get("dgs10")
    sofr    = data.get("sofr")
    rrp     = data.get("rrp")
    nfp     = data.get("nfp")
    cpi     = data.get("cpi")
    unrate  = data.get("unrate")
    ci      = data.get("ci")
    m2      = data.get("m2")
    auction = data.get("auction")

    print("\n  [패치 시작]")

    # ── TGA ──
    if tga:
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>)',
            lambda m: f'{m.group(1)}{tga["bal_b"]:,.1f}B{m.group(2)}',
            re.DOTALL)
        html = sub(html,
            r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
            f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov')
        html = sub(html,
            r'\d+/\d+ DTS Closing \$[\d,.]+B\(전일',
            f'{tga["date"]} DTS Closing {tga["val_str"]}(전일')

    # ── RRP ──
    if rrp:
        html = sub(html,
            r'(<td class="val val-ok">\$)[\d.]+B(</td>\s*<td class="verify">.*?RRPONTSYD)',
            lambda m: f'{m.group(1)}{rrp["val"]:.2f}B{m.group(2)}',
            re.DOTALL)
        html = sub(html,
            r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
            f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B')

    # ── DGS10 ──
    if dgs10:
        html = sub(html,
            r'(<td class="val val-ok">)([\d.]+%)(</td>\s*<td class="verify">.*?FRED DGS10)',
            lambda m: f'{m.group(1)}{dgs10["val"]:.2f}%{m.group(3)}',
            re.DOTALL)
        html = sub(html,
            r'\d+/\d+ 종가 · FRED DGS10',
            f'{dgs10["date"]} 종가 · FRED DGS10')

    # ── SOFR ──
    if sofr:
        html = sub(html,
            r'(<td class="val val-ok">)([\d.]+%)(\ / [\d.]+%</td>)',
            lambda m: f'{m.group(1)}{sofr["val"]:.2f}%{m.group(3)}')
        html = sub(html,
            r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인')
        html = sub(html,
            r'\d+/\d+ SOFR [\d.]+% vs IORB [\d.]+% · 역전 해소',
            f'{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB 3.65% · 역전 해소')

    # ── 국채 경매 Indirect Bidder ──
    if auction:
        html = sub(html,
            r'(vbadge-ok">검색확인</span><span class="verify-note">)\d+Y \d+/\d+ 경매 · fiscaldata 확인',
            f'\\g<1>10Y {auction["date"]} 경매 · fiscaldata 확인')
        # val 셀: "64.14% (30Y)" 형태
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)[\d.]+% \((?:30Y|10Y)\)(</td>)',
            f'\\g<1>{auction["ratio"]}% (10Y)\\g<2>')

    # ── NFP ──
    if nfp:
        nfp_k = int(nfp["val"])
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">3월: \+)[\d,]+K(</td>)',
            f'\\g<1>{nfp_k:,}K\\g<2>')
        html = sub(html,
            r'\d+/\d+ 발표 · BLS 3월 \+[\d,]+K',
            f'{nfp["date"]} 발표 · BLS 3월 +{nfp_k:,}K')

    # ── Core CPI 날짜 ──
    if cpi:
        html = sub(html,
            r'\d+/\d+ 발표 · 3월 BLS 헤드라인',
            f'{cpi["date"]} 발표 · 3월 BLS 헤드라인')

    # ── 실업률 ──
    if unrate:
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)([\d.]+%)(</td>\s*<td class="verify">.*?3월 BLS)',
            lambda m: f'{m.group(1)}{unrate["val"]:.1f}%{m.group(3)}',
            re.DOTALL)
        html = sub(html,
            r'3월 BLS · \d+/\d+ 발표',
            f'3월 BLS · {unrate["date"]} 발표')

    # ── C&I 대출 — verify-note anchor로 정확히 타겟팅 ──
    if ci:
        # note 교체 (vbadge-old → vbadge-ok + 날짜 업데이트)
        old_ci = '<span class="vbadge vbadge-old">구버전</span><span class="verify-note">3월 FRED BUSLOANS · 접근 불가</span>'
        new_ci = f'<span class="vbadge vbadge-ok">검색확인</span><span class="verify-note">{ci["date"]} · FRED BUSLOANS</span>'
        if old_ci in html:
            html = html.replace(old_ci, new_ci)
            print(f"    ✅ C&I note 교체")
        else:
            # 이미 교체된 경우 날짜만 업데이트
            html = sub(html,
                r'\d+/\d+ · FRED BUSLOANS(?=</span>)',
                f'{ci["date"]} · FRED BUSLOANS')
        # val 셀: note 바로 앞 행 (str 직접 교체)
        old_val = f'<td class="val val-ok">${ci["val"]:,.1f}B</td>\n  <td class="verify"><span class="vbadge vbadge-ok">검색확인</span><span class="verify-note">{ci["date"]} · FRED BUSLOANS</span>'
        # 값이 이미 맞으면 skip, 아니면 앞 val 업데이트
        html = sub(html,
            r'(H\.8 C&amp;I[^<]*</span></td>\s*<td[^>]*>[^<]*</td>\s*<td class="val val-(?:ok|warn)">\$)[\d,.]+B(</td>\s*<td class="verify">)',
            lambda m: f'{m.group(1)}{ci["val"]:,.1f}B{m.group(2)}',
            re.DOTALL)

    # ── M2 ──
    if m2:
        html = sub(html,
            r'(Q4 2025 · 분기 데이터</span></td>)',
            f'\\g<1>')  # M2 Velocity는 분기 — val 셀은 건드리지 않음
        # M2SL은 M2 Velocity 아닌 M2 잔액 — 파일에 별도 셀 없으면 스킵
        print(f"    ℹ️  M2: 파일에 M2 잔액 전용 셀 없음, Velocity 셀은 분기 데이터 유지")

    return html


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작\n")

    data = {}
    data["tga"]     = safe_fetch("TGA",      fetch_tga)
    data["dgs10"]   = safe_fetch("DGS10",    lambda: fetch_fred("DGS10"))
    data["sofr"]    = safe_fetch("SOFR",     lambda: fetch_fred("SOFR"))
    data["rrp"]     = safe_fetch("RRP",      lambda: fetch_fred("RRPONTSYD"))
    data["nfp"]     = safe_fetch("NFP",      lambda: fetch_fred("PAYEMS"))
    data["cpi"]     = safe_fetch("CoreCPI",  lambda: fetch_fred("CPILFESL"))
    data["unrate"]  = safe_fetch("UNRATE",   lambda: fetch_fred("UNRATE"))
    data["ci"]      = safe_fetch("C&I",      lambda: fetch_fred("BUSLOANS"))
    data["m2"]      = safe_fetch("M2",       lambda: fetch_fred("M2SL"))
    data["auction"] = safe_fetch("경매IB",   fetch_auction)

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    html = patch_html(html, data)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
