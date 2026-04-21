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


def fetch_nfp():
    """NFP 전월 대비 증감 (단위: 천명)"""
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY 없음")
    params = urllib.parse.urlencode({
        "series_id": "PAYEMS", "api_key": FRED_API_KEY,
        "file_type": "json", "sort_order": "desc", "limit": 3
    })
    data = http_get(f"https://api.stlouisfed.org/fred/series/observations?{params}")
    obs = [o for o in data.get("observations", []) if o["value"] != "."]
    if len(obs) < 2:
        raise ValueError("NFP 데이터 부족")
    latest = float(obs[0]["value"])
    prev   = float(obs[1]["value"])
    change = round(latest - prev)           # 전월 대비 증감 (천명)
    dt = datetime.strptime(obs[0]["date"], "%Y-%m-%d")
    # 발표일은 보통 다음달 첫째 금요일 — verify-note용 date는 월만 표시
    month_name = dt.strftime("%-m월")
    return {
        "val": change,
        "month": month_name,
        "date": f"{dt.month}/{dt.day}",
        "display": f"+{change:,}K ({month_name})"
    }


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





def fetch_spx():
    """S&P 500 종가 — FRED SP500"""
    return fetch_fred("SP500")


def fetch_vix():
    """VIX 종가 — FRED VIXCLS"""
    return fetch_fred("VIXCLS")



def fetch_dxy():
    """DXY 달러 인덱스 — FRED DTWEXBGS (Broad Dollar Index, 일간)"""
    return fetch_fred("DTWEXBGS")


def fetch_cot_ust10y():
    """CFTC COT TFF Futures Only — 10Y UST 레버리지드 펀드 Net 포지션
    publicreporting.cftc.gov CSV API (dataset: udgc-27he)
    헤더: market_and_exchange_names, lev_money_positions_long, lev_money_positions_short
    """
    import io, csv, urllib.parse
    params = urllib.parse.urlencode({
        "$where": "cftc_contract_market_code='043602'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": "1",
        "$select": "market_and_exchange_names,report_date_as_yyyy_mm_dd,lev_money_positions_long,lev_money_positions_short"
    })
    url = f"https://publicreporting.cftc.gov/resource/udgc-27he.csv?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv"
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8")

    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        long_pos  = int(float(row.get("lev_money_positions_long", 0) or 0))
        short_pos = int(float(row.get("lev_money_positions_short", 0) or 0))
        net = long_pos - short_pos
        dt = datetime.strptime(row["report_date_as_yyyy_mm_dd"][:10], "%Y-%m-%d")
        d = f"{dt.month}/{dt.day}"
        direction = "Net Short" if net < 0 else "Net Long"
        contracts_k = abs(net) // 1000
        return {
            "net": net,
            "long": long_pos,
            "short": short_pos,
            "date": d,
            "direction": direction,
            "contracts_k": contracts_k,
            "display": f"{direction} {contracts_k}K계약 ({d})"
        }
    raise ValueError("10Y UST 행 없음")

def ensure_css(html):
    """vbadge-auto CSS 없으면 자동 삽입"""
    if 'vbadge-auto' not in html:
        old = '.vbadge-ss{background:#E6F1FB;color:#0C447C}'
        new = old + '\n.vbadge-auto{background:#EDE7F6;color:#4527A0}'
        html = html.replace(old, new)
        print("  [CSS] vbadge-auto 자동 삽입됨")
    return html


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
    spx     = data.get("spx")
    vix     = data.get("vix")
    dxy     = data.get("dxy")
    cot     = data.get("cot")

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
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
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
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
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
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
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
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+/\d+ SOFR [\d.]+% · FRED 확인',
            f'\\g<1>{AUTO_BADGE}\\g<2>{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인',
            label="SOFR badge")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
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
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)\d+Y \d+/\d+ 경매 · fiscaldata 확인',
            f'\\g<1>{AUTO_BADGE}\\g<2>10Y {auction["date"]} 경매 · fiscaldata 확인',
            label="경매 badge")

    # ── NFP ──
    if nfp:
        nfp_k = nfp["val"]
        month = nfp["month"]
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">\d+월: [+-])[\d,]+K(</td>)',
            f'\\g<1>{nfp_k:,}K\\g<2>', label="NFP val")
        # val 셀 월 이름도 업데이트
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)\d+월: [+-][\d,]+K(</td>)',
            f'\\g<1>{month}: +{nfp_k:,}K\\g<2>', label="NFP val month")
        html = sub(html,
            r'\d+/\d+ 발표 · BLS \d+월 [+-][\d,]+K',
            f'{nfp["date"]} 발표 · BLS {month} +{nfp_k:,}K', label="NFP note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전|자동확인)</span>'
            r'(<span class="verify-note">)\d+/\d+ 발표 · BLS \d+월',
            f'\\g<1>{AUTO_BADGE}\\g<2>{nfp["date"]} 발표 · BLS {month}',
            label="NFP badge")

    # ── Core CPI 날짜 ──
    if cpi:
        html = sub(html,
            r'\d+/\d+ 발표 · 3월 BLS 헤드라인',
            f'{cpi["date"]} 발표 · 3월 BLS 헤드라인', label="CPI note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
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
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전)</span>'
            r'(<span class="verify-note">)3월 BLS · \d+/\d+ 발표',
            f'\\g<1>{AUTO_BADGE}\\g<2>3월 BLS · {unrate["date"]} 발표',
            label="실업률 badge")

    # ── S&P 500 ──
    if spx:
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)([\d,]+\.?\d*?)(<br></td>\s*<td class="verify">.*?SPX)',
            lambda m: f'{m.group(1)}{spx["val"]:,.2f}<br>{m.group(3)}',
            re.DOTALL, "SPX val")
        html = sub(html,
            r'\d+/\d+ 장중 · 종가 미확인 · \d+/\d+ 신고가 [\d,]+',
            f'{spx["date"]} 종가 · FRED SP500', label="SPX note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|est|auto)">(?:검색확인|구버전|추정|자동확인)</span>'
            r'(<span class="verify-note">)\d+/\d+ (?:장중|종가) · (?:종가 미확인 · \d+/\d+ 신고가 [\d,]+|FRED SP500)',
            f'\\g<1>{AUTO_BADGE}\\g<2>{spx["date"]} 종가 · FRED SP500',
            label="SPX badge")

    # ── VIX ──
    if vix:
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)([\d.]+)(</td>\s*<td class="verify">.*?CBOE)',
            lambda m: f'{m.group(1)}{vix["val"]:.2f}{m.group(3)}',
            re.DOTALL, "VIX val")
        html = sub(html,
            r'\d+/\d+ 장중 · CBOE · 종가 아님',
            f'{vix["date"]} 종가 · FRED VIXCLS', label="VIX note")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|est|auto)">(?:검색확인|구버전|추정|자동확인)</span>'
            r'(<span class="verify-note">)\d+/\d+ (?:장중|종가) · (?:CBOE · 종가 아님|FRED VIXCLS)',
            f'\\g<1>{AUTO_BADGE}\\g<2>{vix["date"]} 종가 · FRED VIXCLS',
            label="VIX badge")

    # ── DXY ──
    if dxy:
        # 직접 문자열 교체 (MOVE Index와 패턴 충돌 방지)
        old_dxy = (
            '<td class="val val-warn">97.8</td>\n'
            '  <td class="verify"><span class="vbadge vbadge-ok">검색확인</span>'
            '<span class="verify-note">4/17 종가 · Investing.com</span></td>'
        )
        new_dxy = (
            f'<td class="val val-ok">{dxy["val"]:.1f}</td>\n'
            f'  <td class="verify">{AUTO_BADGE}'
            f'<span class="verify-note">{dxy["date"]} 종가 · FRED DTWEXBGS</span></td>'
        )
        if old_dxy in html:
            html = html.replace(old_dxy, new_dxy)
            print(f"    ✅ DXY 직접 교체")
        else:
            # 이미 교체된 경우 날짜+값만 업데이트
            html = sub(html,
                r'(<td class="val val-(?:ok|warn)">)([\d.]+)(</td>\s*<td class="verify">'
                r'<span class="vbadge vbadge-auto">자동확인</span>'
                r'<span class="verify-note">)\d+/\d+ 종가 · FRED DTWEXBGS(</span></td>)',
                f'\\g<1>{dxy["val"]:.1f}\\g<3>{dxy["date"]} 종가 · FRED DTWEXBGS\\g<4>',
                label="DXY 재업데이트")

    # ── CFTC COT (두 군데) ──
    if cot:
        net_k = abs(cot["net"]) // 1000
        direction = cot["direction"]

        # 1) CFTC COT 국채 선물 val 셀: "Net Short 구조 지속"
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">)Net (?:Short|Long) 구조 지속(</td>)',
            f'\\g<1>{direction} {net_k}K계약\\g<2>',
            label="COT val (국채)")
        html = sub(html,
            r'4/\d+ 기준 · CFTC 접근 불가',
            f'{cot["date"]} · CFTC TFF Lev Funds',
            label="COT note (국채)")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전|자동확인)</span>'
            r'(<span class="verify-note">)\d+/\d+ 기준 · CFTC (?:접근 불가|TFF Lev Funds)',
            f'\\g<1>{AUTO_BADGE}\\g<2>{cot["date"]} · CFTC TFF Lev Funds',
            label="COT badge (국채)")

        # 2) HF 레버리지 숏 val 셀: "~508K계약"
        html = sub(html,
            r'(<td class="val val-(?:ok|warn)">~?)[\d]+K계약(</td>)',
            f'\\g<1>{net_k}K계약\\g<2>',
            label="COT val (HF숏)")
        html = sub(html,
            r'4/\d+ CFTC 기준 · 접근 불가',
            f'{cot["date"]} · CFTC TFF Lev Funds',
            label="COT note (HF숏)")
        html = sub(html,
            r'(<td class="verify">)<span class="vbadge vbadge-(?:ok|old|auto)">(?:검색확인|구버전|자동확인)</span>'
            r'(<span class="verify-note">)\d+/\d+ CFTC 기준 · (?:접근 불가|CFTC TFF Lev Funds)',
            f'\\g<1>{AUTO_BADGE}\\g<2>{cot["date"]} · CFTC TFF Lev Funds',
            label="COT badge (HF숏)")

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
    data["nfp"]     = safe_fetch("NFP",     fetch_nfp)
    data["cpi"]     = safe_fetch("CoreCPI", lambda: fetch_fred("CPILFESL"))
    data["unrate"]  = safe_fetch("UNRATE",  lambda: fetch_fred("UNRATE"))
    data["ci"]      = safe_fetch("C&I",     lambda: fetch_fred("BUSLOANS"))
    data["auction"] = safe_fetch("경매IB",  fetch_auction)
    data["spx"]     = safe_fetch("S&P500",  fetch_spx)
    data["vix"]     = safe_fetch("VIX",     fetch_vix)
    data["dxy"]     = safe_fetch("DXY",     fetch_dxy)
    data["cot"]     = safe_fetch("COT_UST", fetch_cot_ust10y)

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    html = ensure_css(html)
    html = patch_html(html, data)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
