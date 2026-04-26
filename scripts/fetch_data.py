#!/usr/bin/env python3
"""
macro-monitor 자동 업데이트 스크립트 v15
개선: tr id 기반 패치 — DOTALL 광역 패턴 완전 제거
      각 patch_* 함수가 <tr id="row-X"> 블록을 먼저 격리 후 내부만 교체
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import re
import os
import time
from datetime import datetime

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"
AUTO_BADGE = '<span class="vbadge vbadge-auto">자동확인</span>'


# ── 공통 유틸 ────────────────────────────────────────────────────

def http_get(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def http_get_raw(url, retries=3, encoding="utf-8"):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*"
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode(encoding)
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def safe_fetch(name, fn):
    try:
        result = fn()
        print(f"  ✅ {name}: {result.get('display', str(result)[:30])}")
        return result
    except Exception as e:
        print(f"  ⚠️  {name}: 실패 ({e}) — 이전 값 유지")
        return None


# ── tr-id 기반 핵심 헬퍼 ─────────────────────────────────────────

def extract_tr(html, row_id):
    """<tr id="row-X"> ... </tr> 블록 추출. (start, end, inner) 반환"""
    # thead 안의 tr은 id 없으므로 data tr만 매칭
    pattern = re.compile(
        r'(<tr(?:[^>]*) id="' + re.escape(row_id) + r'"[^>]*>)(.*?)(</tr>)',
        re.DOTALL
    )
    m = pattern.search(html)
    if not m:
        return None
    return m  # group(1)=open tag, group(2)=inner, group(3)=close tag


def patch_tr(html, row_id, inner_fn, label=""):
    """row_id로 tr 격리 → inner_fn(inner_html) → 교체"""
    m = extract_tr(html, row_id)
    if not m:
        print(f"    ⚠️  미매칭: {label or row_id}")
        return html
    new_inner = inner_fn(m.group(2))
    new_html = html[:m.start()] + m.group(1) + new_inner + m.group(3) + html[m.end():]
    print(f"    ✅ {label or row_id}")
    return new_html


def set_val(inner, new_val, color_class=None):
    """tr 내부의 val 셀 값만 교체"""
    def replacer(m):
        cls = color_class or m.group(1)
        return f'<td class="val {cls}">{new_val}</td>'
    return re.sub(r'<td class="val (val-\w+)">[^<]*(?:<br>)*</td>', replacer, inner, count=1)


def set_note(inner, new_note_text, anchor_substr):
    """verify-note 안의 텍스트를 anchor_substr 기준으로 교체"""
    if anchor_substr not in inner:
        return inner  # anchor 없으면 스킵 (경고는 patch_tr 레벨에서)
    return re.sub(
        r'(<span class="verify-note">)[^<]*(</span>)',
        lambda m: m.group(1) + new_note_text + m.group(2),
        inner, count=1
    )


def set_badge_auto(inner):
    """배지를 자동확인으로 업그레이드"""
    return re.sub(
        r'<span class="vbadge vbadge-(?:ok|old|ss|est)">[^<]+</span>',
        AUTO_BADGE, inner, count=1
    )


# ── 데이터 조회 (변경 없음) ──────────────────────────────────────

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
    raise ValueError("TGA Closing Balance 없음")


def fetch_auction(term="10-Year", sec_type="Note"):
    url = (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
        "/v1/accounting/od/auctions_query"
        f"?fields=auction_date,indirect_bidder_accepted,comp_accepted"
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
    prev = float(obs[1]["value"])
    change = round(latest - prev)
    dt = datetime.strptime(obs[0]["date"], "%Y-%m-%d")
    month_name = f"{dt.month}월"
    return {"val": change, "month": month_name, "date": f"{dt.month}/{dt.day}",
            "display": f"+{change:,}K ({month_name})"}


def fetch_cot_ust10y():
    import io, csv
    params = urllib.parse.urlencode({
        "$where": "cftc_contract_market_code='043602'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": "1",
        "$select": "report_date_as_yyyy_mm_dd,lev_money_positions_long,lev_money_positions_short"
    })
    url = f"https://publicreporting.cftc.gov/resource/udgc-27he.csv?{params}"
    raw = http_get_raw(url)
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        long_pos = int(float(row.get("lev_money_positions_long", 0) or 0))
        short_pos = int(float(row.get("lev_money_positions_short", 0) or 0))
        net = long_pos - short_pos
        dt = datetime.strptime(row["report_date_as_yyyy_mm_dd"][:10], "%Y-%m-%d")
        d = f"{dt.month}/{dt.day}"
        direction = "Net Short" if net < 0 else "Net Long"
        contracts_k = abs(net) // 1000
        return {"net": net, "date": d, "direction": direction,
                "contracts_k": contracts_k,
                "display": f"{direction} {contracts_k}K계약 ({d})"}
    raise ValueError("043602 행 없음")


def fetch_reserves():
    r = fetch_fred("WRBWFRBL")
    r["val_b"] = r["val"] / 1_000
    r["display"] = f'${r["val_b"]:,.0f}B ({r["date"]})'
    return r


def fetch_walcl():
    r = fetch_fred("WALCL")
    r["val_b"] = r["val"] / 1_000
    r["display"] = f'${r["val_b"]:,.0f}B ({r["date"]})'
    return r


def fetch_deposits():
    r = fetch_fred("DPSACBW027SBOG")
    r["display"] = f'${r["val"]:,.0f}B ({r["date"]})'
    return r


def fetch_fhlb():
    r = fetch_fred("BOGZ1FL403069330Q")
    r["val_b"] = r["val"] / 1_000
    r["display"] = f'${r["val_b"]:,.1f}B ({r["date"]})'
    return r


def fetch_oas(series_id):
    return fetch_fred(series_id)


# ── 지표별 패치 함수 (tr-id 기반) ────────────────────────────────

def patch_tga(html, tga):
    if not tga:
        return html
    def inner(s):
        s = set_val(s, tga["val_str"],
                    "val-warn" if tga["bal_b"] < 500 else "val-ok")
        s = re.sub(r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
                   f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov', s)
        s = re.sub(r'\d+/\d+ DTS Closing \$[\d,.]+B\(전일',
                   f'{tga["date"]} DTS Closing {tga["val_str"]}(전일', s)
        return s
    return patch_tr(html, "row-tga", inner, "TGA")


def patch_rrp(html, rrp):
    if not rrp:
        return html
    def inner(s):
        s = set_val(s, f'${rrp["val"]:.2f}B', "val-ok")
        s = re.sub(r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
                   f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B', s)
        return s
    return patch_tr(html, "row-rrp", inner, "RRP")


def patch_dgs10(html, dgs10):
    if not dgs10:
        return html
    def inner(s):
        s = set_val(s, f'{dgs10["val"]:.2f}%', "val-ok")
        s = re.sub(r'\d+/\d+ 종가 · FRED DGS10',
                   f'{dgs10["date"]} 종가 · FRED DGS10', s)
        return s
    return patch_tr(html, "row-dgs10", inner, "DGS10")


def patch_sofr(html, sofr):
    if not sofr:
        return html
    def inner(s):
        # val: "X.XX% / Y.YY%" 형식 — 앞 숫자만 교체
        s = re.sub(r'(>\s*)[\d.]+(%\s*/\s*[\d.]+%\s*</td>)',
                   lambda m: f'{m.group(1)}{sofr["val"]:.2f}{m.group(2)}', s, count=1)
        s = re.sub(r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
                   f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인', s)
        return s
    return patch_tr(html, "row-sofr", inner, "SOFR")


def patch_auction(html, auction):
    if not auction:
        return html
    def inner(s):
        s = re.sub(r'[\d.]+% \((?:30Y|10Y)\)',
                   f'{auction["ratio"]}% (10Y)', s, count=1)
        s = re.sub(r'\d+Y \d+/\d+ 경매 · fiscaldata 확인',
                   f'10Y {auction["date"]} 경매 · fiscaldata 확인', s)
        return s
    return patch_tr(html, "row-auction", inner, "경매IB")


def patch_nfp(html, nfp):
    if not nfp:
        return html
    def inner(s):
        s = re.sub(r'\d+월: [+-][\d,]+K',
                   f'{nfp["month"]}: +{nfp["val"]:,}K', s, count=1)
        s = re.sub(r'\d+/\d+ 발표 · BLS \d+월 [+-][\d,]+K',
                   f'{nfp["date"]} 발표 · BLS {nfp["month"]} +{nfp["val"]:,}K', s)
        return s
    return patch_tr(html, "row-nfp", inner, "NFP")


def patch_cpi(html, cpi):
    if not cpi:
        return html
    def inner(s):
        s = re.sub(r'\d+/\d+ 발표 · \d+월 BLS 헤드라인',
                   f'{cpi["date"]} 발표 · 3월 BLS 헤드라인', s)
        return s
    return patch_tr(html, "row-cpi", inner, "CPI")


def patch_unrate(html, unrate):
    if not unrate:
        return html
    def inner(s):
        s = set_val(s, f'{unrate["val"]:.1f}%',
                    "val-warn" if unrate["val"] >= 4.5 else "val-ok")
        s = re.sub(r'\d월 BLS · \d+/\d+ 발표',
                   f'3월 BLS · {unrate["date"]} 발표', s)
        return s
    return patch_tr(html, "row-unrate", inner, "실업률")


def patch_ci(html, ci):
    if not ci:
        return html
    def inner(s):
        s = set_badge_auto(s)
        s = re.sub(r'\d+/\d+ · FRED BUSLOANS',
                   f'{ci["date"]} · FRED BUSLOANS', s)
        return s
    return patch_tr(html, "row-ci", inner, "C&I")


def patch_spx(html, spx):
    if not spx:
        return html
    def inner(s):
        # val에 <br> 태그 포함 케이스 처리
        s = re.sub(r'(<td class="val val-\w+">)[\d,]+\.?\d*(<br>(?:<br>)?</td>)',
                   lambda m: f'{m.group(1)}{spx["val"]:,.2f}{m.group(2)}', s, count=1)
        s = re.sub(r'\d+/\d+ 종가 · FRED SP500',
                   f'{spx["date"]} 종가 · FRED SP500', s)
        return s
    return patch_tr(html, "row-spx", inner, "SPX")


def patch_vix(html, vix):
    """VIX — row-vix 격리 후 내부만 교체. STLFSI4 행과 교차 불가"""
    if not vix:
        return html
    def inner(s):
        color = "val-warn" if vix["val"] >= 20 else "val-ok"
        s = set_val(s, f'{vix["val"]:.2f}', color)
        s = re.sub(r'\d+/\d+ 종가 · FRED VIXCLS',
                   f'{vix["date"]} 종가 · FRED VIXCLS', s)
        return s
    return patch_tr(html, "row-vix", inner, "VIX")


def patch_stlfsi(html, stlfsi):
    """STLFSI4 — row-stlfsi 격리. VIX 행과 교차 불가"""
    if not stlfsi:
        return html
    def inner(s):
        s = set_val(s, f'{stlfsi["val"]:.3f}', "val-ok")
        s = re.sub(r'\d+/\d+ · FRED STLFSI4',
                   f'{stlfsi["date"]} · FRED STLFSI4', s)
        return s
    return patch_tr(html, "row-stlfsi", inner, "STLFSI4")


def patch_dxy(html, dxy):
    if not dxy:
        return html
    def inner(s):
        s = set_val(s, f'{dxy["val"]:.3f}', "val-ok")
        s = set_badge_auto(s)
        s = re.sub(r'\d+/\d+ 종가 · (?:Investing\.com|FRED DTWEXBGS)',
                   f'{dxy["date"]} 종가 · FRED DTWEXBGS', s)
        return s
    return patch_tr(html, "row-dxy", inner, "DXY")


def patch_cot(html, cot):
    if not cot:
        return html
    net_k = abs(cot["net"]) // 1000
    direction = cot["direction"]
    # COT 국채 선물 행
    def inner_cot(s):
        s = re.sub(r'Net (?:Short|Long) [\d,]+K계약',
                   f'{direction} {net_k:,}K계약', s, count=1)
        s = re.sub(r'\d+/\d+ · CFTC TFF Lev Funds',
                   f'{cot["date"]} · CFTC TFF Lev Funds', s)
        s = set_badge_auto(s)
        return s
    html = patch_tr(html, "row-cot", inner_cot, "COT 국채")
    # HF 레버리지 숏 행
    def inner_hf(s):
        s = re.sub(r'~?[\d,]+K계약',
                   f'{net_k:,}K계약', s, count=1)
        s = re.sub(r'\d+/\d+ · CFTC TFF Lev Funds',
                   f'{cot["date"]} · CFTC TFF Lev Funds', s)
        s = set_badge_auto(s)
        return s
    html = patch_tr(html, "row-hf-short", inner_hf, "HF숏")
    return html


def patch_brent(html, brent):
    if not brent:
        return html
    def inner(s):
        s = set_val(s, f'${brent["val"]:.1f}',
                    "val-alert" if brent["val"] >= 100 else "val-warn")
        s = set_badge_auto(s)
        s = re.sub(r'\d+/\d+ 종가 · (?:FRED DCOILBRENTEU|tradingeconomics/ICE)',
                   f'{brent["date"]} 종가 · FRED DCOILBRENTEU', s)
        return s
    return patch_tr(html, "row-brent", inner, "Brent")


def patch_wti(html, wti):
    if not wti:
        return html
    def inner(s):
        s = set_val(s, f'${wti["val"]:.1f}',
                    "val-alert" if wti["val"] >= 90 else "val-warn")
        s = set_badge_auto(s)
        s = re.sub(r'\d+/\d+ 종가 · (?:FRED DCOILWTICO|Investing\.com/NYMEX)',
                   f'{wti["date"]} 종가 · FRED DCOILWTICO', s)
        return s
    return patch_tr(html, "row-wti", inner, "WTI")


def patch_ig_oas(html, ig):
    if not ig:
        return html
    bp = round(ig["val"] * 100)
    def inner(s):
        s = re.sub(r'\d+bp', f'{bp}bp', s, count=1)
        s = re.sub(r'FRED \d+/\d+ · [\d.]+% · BAMLC0A0CM',
                   f'FRED {ig["date"]} · {ig["val"]:.2f}% · BAMLC0A0CM', s)
        return s
    return patch_tr(html, "row-ig-oas", inner, "IG OAS")


def patch_hy_oas(html, hy):
    if not hy:
        return html
    bp = round(hy["val"] * 100)
    def inner(s):
        s = re.sub(r'\d+bp', f'{bp}bp', s, count=1)
        s = re.sub(r'FRED \d+/\d+ · [\d.]+% · BAMLH0A0HYM2',
                   f'FRED {hy["date"]} · {hy["val"]:.2f}% · BAMLH0A0HYM2', s)
        return s
    return patch_tr(html, "row-hy-oas", inner, "HY OAS")


def patch_reserves(html, res):
    if not res:
        return html
    val_b = res["val"] / 1_000
    def inner(s):
        s = set_val(s, f'${val_b:,.0f}B',
                    "val-warn" if val_b < 3000 else "val-ok")
        s = re.sub(r'\d+/\d+ · FRED WRBWFRBL',
                   f'{res["date"]} · FRED WRBWFRBL', s)
        return s
    return patch_tr(html, "row-reserves", inner, "지준")


def patch_walcl(html, walcl):
    if not walcl:
        return html
    val_b = walcl["val"] / 1_000
    def inner(s):
        s = set_val(s, f'${val_b:,.0f}B', "val-ok")
        s = re.sub(r'\d+/\d+ · FRED WALCL',
                   f'{walcl["date"]} · FRED WALCL', s)
        return s
    return patch_tr(html, "row-walcl", inner, "WALCL")


def patch_deposits(html, dep):
    if not dep:
        return html
    def inner(s):
        s = set_val(s, f'${dep["val"]:,.0f}B', "val-ok")
        s = re.sub(r'\d+/\d+ · FRED DPSACBW027SBOG',
                   f'{dep["date"]} · FRED DPSACBW027SBOG', s)
        return s
    return patch_tr(html, "row-deposits", inner, "예금")


def patch_usdjpy(html, usdjpy):
    if not usdjpy:
        return html
    def inner(s):
        s = set_val(s, f'{usdjpy["val"]:.2f}', "val-ok")
        s = set_badge_auto(s)
        s = re.sub(r'\d+/\d+ 종가 · FRED DEXJPUS',
                   f'{usdjpy["date"]} 종가 · FRED DEXJPUS', s)
        return s
    return patch_tr(html, "row-usdjpy", inner, "USD/JPY")


def patch_fhlb(html, fhlb):
    if not fhlb:
        return html
    val_b = fhlb["val"] / 1_000
    def inner(s):
        s = set_val(s, f'${val_b:,.1f}B', "val-ok")
        s = set_badge_auto(s)
        s = re.sub(r'Q\d 20\d\d · (?:FRED Z\.1 \(FHLB 공식≈\$[\d.]+B\)|FHLB[^<]*)',
                   f'Q4 {fhlb["date"][:4]} · FRED Z.1 (FHLB 공식≈$676.7B)', s)
        return s
    return patch_tr(html, "row-fhlb", inner, "FHLB")


# ── CSS 보장 ─────────────────────────────────────────────────────

def ensure_css(html):
    if 'vbadge-auto' not in html:
        old = '.vbadge-ss{background:#E6F1FB;color:#0C447C}'
        new = old + '\n.vbadge-auto{background:#EDE7F6;color:#4527A0}'
        html = html.replace(old, new)
        print("  [CSS] vbadge-auto 삽입됨")
    return html


# ── 검증 ─────────────────────────────────────────────────────────

def validate_patches(html, data):
    missing = []
    skip = {"cpi", "ci"}
    for key, val in data.items():
        if not val or key in skip:
            continue
        date = val.get("date", "")
        if date and date not in html:
            missing.append(f"{key}({date})")
    if missing:
        print(f"  ⚠️  패치 후 날짜 미반영 의심: {', '.join(missing)}")
    else:
        print(f"  ✅ 패치 검증 OK")


# ── 메인 ─────────────────────────────────────────────────────────

def patch_html(html, data):
    print("\n  [패치 시작]")
    html = patch_tga(html,      data.get("tga"))
    html = patch_rrp(html,      data.get("rrp"))
    html = patch_dgs10(html,    data.get("dgs10"))
    html = patch_sofr(html,     data.get("sofr"))
    html = patch_auction(html,  data.get("auction"))
    html = patch_nfp(html,      data.get("nfp"))
    html = patch_cpi(html,      data.get("cpi"))
    html = patch_unrate(html,   data.get("unrate"))
    html = patch_ci(html,       data.get("ci"))
    html = patch_spx(html,      data.get("spx"))
    html = patch_vix(html,      data.get("vix"))
    html = patch_stlfsi(html,   data.get("stlfsi"))
    html = patch_dxy(html,      data.get("dxy"))
    html = patch_cot(html,      data.get("cot"))
    html = patch_brent(html,    data.get("brent"))
    html = patch_wti(html,      data.get("wti"))
    html = patch_ig_oas(html,   data.get("ig_oas"))
    html = patch_hy_oas(html,   data.get("hy_oas"))
    html = patch_reserves(html, data.get("reserves"))
    html = patch_walcl(html,    data.get("walcl"))
    html = patch_deposits(html, data.get("deposits"))
    html = patch_fhlb(html,     data.get("fhlb"))
    html = patch_usdjpy(html,   data.get("usdjpy"))
    return html


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 데이터 조회 시작\n")

    data = {}
    data["tga"]      = safe_fetch("TGA",      fetch_tga)
    data["dgs10"]    = safe_fetch("DGS10",    lambda: fetch_fred("DGS10"))
    data["sofr"]     = safe_fetch("SOFR",     lambda: fetch_fred("SOFR"))
    data["rrp"]      = safe_fetch("RRP",      lambda: fetch_fred("RRPONTSYD"))
    data["nfp"]      = safe_fetch("NFP",      fetch_nfp)
    data["cpi"]      = safe_fetch("CoreCPI",  lambda: fetch_fred("CPILFESL"))
    data["unrate"]   = safe_fetch("UNRATE",   lambda: fetch_fred("UNRATE"))
    data["ci"]       = safe_fetch("C&I",      lambda: fetch_fred("BUSLOANS"))
    data["auction"]  = safe_fetch("경매IB",   fetch_auction)
    data["spx"]      = safe_fetch("S&P500",   lambda: fetch_fred("SP500"))
    data["vix"]      = safe_fetch("VIX",      lambda: fetch_fred("VIXCLS"))
    data["stlfsi"]   = safe_fetch("STLFSI4",  lambda: fetch_fred("STLFSI4"))
    data["dxy"]      = safe_fetch("DXY",      lambda: fetch_fred("DTWEXBGS"))
    data["cot"]      = safe_fetch("COT_UST",  fetch_cot_ust10y)
    data["brent"]    = safe_fetch("Brent",    lambda: fetch_fred("DCOILBRENTEU"))
    data["wti"]      = safe_fetch("WTI",      lambda: fetch_fred("DCOILWTICO"))
    data["ig_oas"]   = safe_fetch("IG OAS",   lambda: fetch_oas("BAMLC0A0CM"))
    data["hy_oas"]   = safe_fetch("HY OAS",   lambda: fetch_oas("BAMLH0A0HYM2"))
    data["reserves"] = safe_fetch("지준",      fetch_reserves)
    data["walcl"]    = safe_fetch("WALCL",     fetch_walcl)
    data["deposits"] = safe_fetch("예금",      fetch_deposits)
    data["fhlb"]     = safe_fetch("FHLB",      fetch_fhlb)
    data["usdjpy"]   = safe_fetch("USD/JPY",   lambda: fetch_fred("DEXJPUS"))

    with open(MONITOR_FILE, encoding="utf-8") as f:
        html = f.read()

    html = ensure_css(html)
    html = patch_html(html, data)
    validate_patches(html, data)

    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  완료: {MONITOR_FILE} 업데이트됨")


if __name__ == "__main__":
    main()
