#!/usr/bin/env python3
# ========================================================================
# macro-monitor 자동 업데이트 스크립트 v17.4
# v17.4 (8/15):
#   - [긴급수정] fetch_cpi가 SA 시리즈(CPIAUCSL/CPILFESL)로 YoY를 계산해 실제 BLS
#     발표치와 어긋남(헤드라인 -10bp, 코어 -30bp). BLS 보도자료 관행인 NSA
#     시리즈(CPIAUCNS/CPILFENS)로 교체. 7월 실측 대조: 헤드라인 3.4%·코어 2.5%.
# v17.3 (8/15):
#   - [구조] IORB 하드코딩 제거 → FRED 시리즈 IORB 조회. FOMC 금리 변경 시
#     아무도 모르게 Repo 스프레드가 틀어지던 함정 제거. 조회 실패 시에만 폴백.
#   - [재보정] Repo 판단 임계를 GCF 기준(+20/+30bp)에서 SOFR-IORB 기준으로 교체.
#     기존 임계로는 경보가 영원히 울리지 않는 구조였음(0bp 역전이 실질 신호).
# v17.2 (8/15):
#   - [긴급수정] v17.1 리팩터링 중 fetch_unrate가 삭제되어 실행 시 NameError.
#     py_compile은 통과하고 patch 단계만 mock 테스트해서 배포 후에야 발견됨.
#   - [재발방지] preflight(): main이 참조하는 fetcher 이름을 네트워크 호출 전에 검증.
# v17.1 (8/15):
#   - [회귀수정] patch_cpi 정규식이 val 셀의 수동 헤드라인 값까지 삼켜 삭제.
#     ("헤드라인 3.8%(수동) / Core 2.8%" → "Core 2.8%" 로 조용히 사라짐)
#     val 셀을 통째로 재작성하는 방식으로 교체.
#   - [오판정정] v17은 "헤드라인 CPI는 FRED 단일 시리즈로 확정 어려움"이라 봤으나
#     CPIAUCSL이 그대로 헤드라인 CPI다. 헤드라인·Core 모두 자동화해 수동 의존 제거.
# v17 (8/15):
#   - [치명] 자기 오염(self-poisoning) 버그 3건 수정 + 구조적 재발 방지.
#     쓰는 형식과 읽는 앵커가 달라 "패치 성공한 순간 스스로 잠기는" 버그.
#     ① NFP: f"+{change}K"가 음수에서 "+-23K" 생성 → 앵커 [+-][\d,]+K가 못 읽음.
#        7월 고용이 마이너스로 꺾인 순간 지표가 멈춤. 부호 포맷을 {:+,}로 통일.
#     ② FHLB: 앵커는 "Q\d 20\d\d · FHLB"인데 쓰는 값은 "· FRED Z.1 (...)" → 1회만 동작.
#        + "Q4" 하드코딩으로 분기 오표기. 실제 분기 산출로 교체.
#     ③ TGA threshold: 앵커 "(전일"이 본문에 존재하지 않음(오래전부터 사망) → 제거.
#   - [신규] ANCHORS 라운드트립 검증: 패치가 쓴 결과를 자기 앵커로 다시 읽어
#     실패하면 즉시 경고. 자기 오염이 조용히 묻히는 것을 원천 차단.
#   - [수정] Repo Stress: val 패치 부재로 284bp 화석값 방치 → SOFR-IORB(bp) 패치 추가.
#     note만 갱신되고 val은 고정돼 "값 284bp / 설명 -3bp" 모순 발생했던 건.
#   - [수정] CPI: 기존 patch_cpi는 값을 쓰지 않고 날짜만 교체 + "3월" 하드코딩 =
#     사실상 미구현. CPILFESL(지수 레벨)에서 Core YoY(%)를 직접 계산해 patch.
#   - [제외] C&I: FRED BUSLOANS(월간)와 파일의 H.8(주간)은 개념이 다른 숫자.
#     한 셀을 두고 충돌하므로 자동 패치 대상에서 공식 제외(H.8 수동 관리 일원화).
#   - [제거] validate_patches의 skip={"cpi","ci"} 예외. 실패를 조용히 감추던 원인.
#
# v16 (5/30):
#   - [하드닝] patch_rrp/dgs10/spx/brent/wti/unrate 의 val 교체를
#     lazy DOTALL(.*?ANCHOR) → note-anchor 방식으로 전환.
#     (코딩 규칙: val 셀 교체 시 DOTALL 광역 패턴 금지)
# v14:
#   - Brent/WTI FRED 자동확인 추가, http_get retry, patch_html 함수 분리
#
# [자동 패치 항목]
#   TGA, RRP, DGS10, SOFR, Repo(SOFR-IORB), 경매IB(10Y), NFP, CoreCPI(YoY 계산),
#   실업률, SPX, VIX, DXY, COT(UST10Y), Brent, WTI, IG/HY OAS, 지준, WALCL, 예금,
#   FHLB, USDJPY, STLFSI
#
# [자동 패치 제외 — 수동 갱신 (스크립트가 건드리지 않음)]
#   H.8 전 항목(Non-MBS line5, NDFI line26, 외국계 Table10 line5, 기타대출 line27,
#   Large Time, C&I ← v17에서 추가), MMF, MOVE, 스왑스프레드, EU Bank CDS,
#   BDC PIK, BTC, Gold, TIC, CLARITY, SLOOS, M2V
#
# [IORB 주의] FOMC가 금리를 변경하면 아래 IORB 상수를 반드시 갱신할 것.
# ========================================================================

import urllib.request
import urllib.parse
import urllib.error
import json
import re
import os
import time
from datetime import datetime

SCRIPT_VERSION = "v17.4"

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
MONITOR_FILE = "monitor.html"
AUTO_BADGE = '<span class="vbadge vbadge-auto">자동확인</span>'

# v17.3: IORB 하드코딩 제거. FRED 시리즈 "IORB"로 직접 조회한다.
# 상수로 두면 FOMC가 금리를 바꿔도 아무도 모르게 Repo 스프레드가 틀어진다
# (주석으로 "갱신 필수"라고 적어두는 것은 구조적 방지책이 아니다).
# 조회 실패 시에만 아래 폴백을 쓰고, 그 사실을 로그에 명시한다.
IORB_FALLBACK = 3.65

# ── 라운드트립 앵커 레지스트리 ──────────────────────────────────
# 패치가 "쓴 결과"를 자기 "읽기 앵커"로 다시 읽을 수 있는지 검증한다.
# 읽기 앵커와 쓰기 포맷이 어긋나면 패치는 딱 한 번만 성공하고 영구 잠긴다
# (v16까지 NFP·FHLB에서 실제 발생). 여기에 등록해두면 즉시 잡힌다.
ANCHORS = []


def register_anchor(label, regex):
    """패치 성공 시 호출 — 이후 verify_anchors()가 재판독 가능 여부를 확인"""
    ANCHORS.append((label, regex))


def verify_anchors(html):
    """패치 후 각 앵커가 여전히 매칭되는지 확인 (자기 오염 탐지)"""
    broken = [lbl for lbl, rx in ANCHORS if not re.search(rx, html)]
    if broken:
        print(f"  \U0001F534 자기오염 의심 — 쓴 값을 자기 앵커가 다시 못 읽음: {', '.join(broken)}")
    else:
        print(f"  \u2705 앵커 라운드트립 OK ({len(ANCHORS)}건)")
    return broken


# ── 공통 유틸 ────────────────────────────────────────────────────

def http_get(url, retries=3):
    """HTTP GET with retry (exponential backoff)"""
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
    """HTTP GET raw text (CSV 등)"""
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
    """실패해도 None 반환 — 이전 값 유지"""
    try:
        result = fn()
        print(f"  ✅ {name}: {result.get('display', str(result)[:30])}")
        return result
    except Exception as e:
        print(f"  ⚠️  {name}: 실패 ({e}) — 이전 값 유지")
        return None


def sub(html, pattern, replacement, flags=0, label=""):
    """regex 교체 + 결과 로깅"""
    result, n = re.subn(pattern, replacement, html, flags=flags)
    tag = label or pattern[:45]
    if n == 0:
        print(f"    ⚠️  미매칭: {tag}")
    else:
        print(f"    ✅ {n}건: {tag}")
    return result


def _patch_val_by_note(html, note_regex, new_note, val_regex, val_repl, label):
    """note-anchor val 교체 (DOTALL 미사용).
    1) note 정규식으로 위치 확정  2) note 교체
    3) note 직전 마지막 <td class="val ...> 셀만 bounded 교체.
    row가 추가/삭제돼도 .*? 가 인접하지 않은 셀을 잡는 오매칭이 발생하지 않음."""
    m = re.search(note_regex, html)
    if not m:
        print(f"    ⚠️  미매칭: {label}")
        return html
    pos = m.start()
    html = html[:pos] + new_note + html[m.end():]          # note 먼저 교체 (pos 고정)
    seg_start = html.rfind('<td class="val', 0, pos)        # note 직전 val 셀 시작
    if seg_start == -1:
        print(f"    ⚠️  val 셀 못 찾음: {label}")
        return html
    segment = html[seg_start:pos]                           # val~note 직전까지 bounded
    # v17: segment는 이미 val~note 사이로 bounded돼 있으므로 DOTALL을 써도
    #      인접하지 않은 셀을 잡을 위험이 없다(코딩 규칙의 금지 대상은 광역 DOTALL).
    #      중첩 <span>이 있는 val 셀을 처리하기 위해 필요.
    new_segment, n = re.subn(val_regex, val_repl, segment, count=1, flags=re.S)
    if n == 0:
        print(f"    ⚠️  val 미매칭: {label}")
        return html
    html = html[:seg_start] + new_segment + html[pos:]
    print(f"    ✅ {label}")
    return html


# ── 데이터 조회 ──────────────────────────────────────────────────

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
            return {"val": val, "date": d, "month": f"{dt.month}월",
                    "display": f"{val} ({d})"}
    raise ValueError(f"{series_id} 없음")


def fetch_nfp():
    """NFP 전월 대비 증감 (천명)"""
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
    # v17: 부호 하드코딩('+') 금지. 음수일 때 "+-23K"가 생성되어
    # 자기 앵커 [+-][\d,]+K 가 다시 못 읽는 자기 오염이 발생했음.
    return {"val": change, "month": month_name, "date": f"{dt.month}/{dt.day}",
            "signed": f"{change:+,}K",
            "display": f"{change:+,}K ({month_name})"}


def _yoy_from_fred(series_id, label):
    """FRED 지수 시리즈에서 전년 동월 대비(%) 계산 — 13개월치 필요"""
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY 없음")
    params = urllib.parse.urlencode({
        "series_id": series_id, "api_key": FRED_API_KEY,
        "file_type": "json", "sort_order": "desc", "limit": 16
    })
    data = http_get(f"https://api.stlouisfed.org/fred/series/observations?{params}")
    obs = [o for o in data.get("observations", []) if o["value"] != "."]
    if len(obs) < 13:
        raise ValueError(f"{label} 데이터 부족(13개월 필요)")
    latest = float(obs[0]["value"])
    year_ago = float(obs[12]["value"])
    dt = datetime.strptime(obs[0]["date"], "%Y-%m-%d")
    return {"yoy": round((latest / year_ago - 1) * 100, 1),
            "index": latest, "dt": dt}


def fetch_cpi():
    """헤드라인(CPIAUCSL) + Core(CPILFESL) YoY 동시 산출.

    v17.1: v17에서 '헤드라인은 FRED 단일 시리즈로 확정이 어렵다'고 보고 Core만
    자동화했으나 이는 오판이었다. CPIAUCSL이 그대로 헤드라인 CPI다.
    더 나쁜 건, Core만 패치하는 정규식이 val 셀의 수동 헤드라인 값까지
    삼켜서 지워버렸고(값 셀엔 Core만 남고 임계 서술은 '헤드라인 수동 유지'라고
    말하는 불일치 발생), 이는 이 스크립트가 없애려던 문제 그 자체였다.
    둘 다 자동화해 수동 의존을 제거한다."""
    # v17.4: BLS 보도자료의 "전년동월비"는 NSA(계절조정 전) 기준이다
    # ("...increased 3.4 percent before seasonal adjustment"). v17.1은 SA
    # 시리즈(CPIAUCSL/CPILFESL)로 계산해 실제 BLS 발표치(헤드라인 3.4%·코어 2.5%,
    # 2026년 7월 기준)와 각각 10bp·30bp 어긋났다(계산값 3.5%/2.8%). NSA 시리즈로 교체.
    core = _yoy_from_fred("CPILFENS", "Core CPI(NSA)")
    head = _yoy_from_fred("CPIAUCNS", "헤드라인 CPI(NSA)")
    dt = core["dt"]
    return {"val": core["yoy"], "core": core["yoy"], "headline": head["yoy"],
            "index": core["index"], "month": f"{dt.month}월",
            "date": f"{dt.month}/{dt.day}",
            "display": f'헤드라인 {head["yoy"]:.1f}% / Core {core["yoy"]:.1f}% ({dt.month}월)'}


def fetch_iorb():
    """IORB(지준부리금리) — FRED 시리즈 IORB. v17.3에서 하드코딩 대체."""
    return fetch_fred("IORB")


def fetch_unrate():
    """실업률 — FRED UNRATE. note에 월 표기를 넣기 위해 month 필드를 함께 사용."""
    return fetch_fred("UNRATE")


def fetch_cot_ust10y():
    """CFTC TFF — 10Y UST 레버리지드 펀드 Net 포지션 (계약코드 043602)"""
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


def fetch_oil(series_id):
    """Brent(DCOILBRENTEU) / WTI(DCOILWTICO) — FRED, 전일 종가"""
    return fetch_fred(series_id)


# ── CSS 보장 ────────────────────────────────────────────────────


def fetch_reserves():
    """은행 지준 잔고 — FRED WRBWFRBL (H.4.1 주간, 단위: 백만달러)"""
    r = fetch_fred("WRBWFRBL")
    r["val_b"] = r["val"] / 1_000  # M → B
    r["display"] = f'${r["val_b"]:,.0f}B ({r["date"]})'
    return r


def fetch_walcl():
    """Fed 대차대조표 총자산 — FRED WALCL (H.4.1 주간, 단위: 백만달러)"""
    r = fetch_fred("WALCL")
    r["val_b"] = r["val"] / 1_000
    r["display"] = f'${r["val_b"]:,.0f}B ({r["date"]})'
    return r


def fetch_deposits():
    """은행 예금 총액 — FRED DPSACBW027SBOG (H.8 주간, 단위: 십억달러)"""
    r = fetch_fred("DPSACBW027SBOG")
    r["display"] = f'${r["val"]:,.0f}B ({r["date"]})'
    return r



def fetch_usdjpy():
    """USD/JPY 환율 — FRED DEXJPUS (일간)"""
    return fetch_fred("DEXJPUS")


def fetch_stlfsi():
    """St. Louis Fed 금융 스트레스 지수 — FRED STLFSI4 (주간)"""
    return fetch_fred("STLFSI4")

def fetch_fhlb():
    """FHLB Advances — FRED BOGZ1FL403069330Q (Fed Financial Accounts Z.1, 분기)
    FHLB 공식 보고서($676.7B)와 ~$10B 차이 — 집계 방식 상이, 추세 추적용으로 동일하게 유효
    공식 수치: https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-combined-financial-report
    """
    r = fetch_fred("BOGZ1FL403069330Q")
    r["val_b"] = r["val"] / 1_000
    # v17: 분기 시리즈인데 fetch_fred가 {month}/{day}만 만들어 "1/1"로 찍혔고,
    #      patch_fhlb는 "Q4"를 하드코딩해 분기를 오표기했다. 실제 분기를 산출한다.
    r["quarter"] = "?"
    r["year"] = "?"
    if not FRED_API_KEY:
        return r
    try:
        params = urllib.parse.urlencode({
            "series_id": "BOGZ1FL403069330Q", "api_key": FRED_API_KEY,
            "file_type": "json", "sort_order": "desc", "limit": 5
        })
        data = http_get(f"https://api.stlouisfed.org/fred/series/observations?{params}")
        for obs in data.get("observations", []):
            if obs["value"] != ".":
                dt = datetime.strptime(obs["date"], "%Y-%m-%d")
                r["quarter"] = f"Q{(dt.month - 1) // 3 + 1}"
                r["year"] = str(dt.year)
                r["date"] = f'{r["quarter"]} {r["year"]}'   # "1/1" 대신 "Q1 2026"
                break
    except Exception:
        pass
    r["display"] = f'${r["val_b"]:,.1f}B ({r["date"]})'
    return r

def fetch_oas(series_id):
    """IG OAS(BAMLC0A0CM) / HY OAS(BAMLH0A0HYM2) — FRED, 단위: %"""
    return fetch_fred(series_id)


def ensure_css(html):
    if 'vbadge-auto' not in html:
        old = '.vbadge-ss{background:#E6F1FB;color:#0C447C}'
        new = old + '\n.vbadge-auto{background:#EDE7F6;color:#4527A0}'
        html = html.replace(old, new)
        print("  [CSS] vbadge-auto 삽입됨")
    return html


# ── 지표별 패치 함수 ─────────────────────────────────────────────

def patch_tga(html, tga):
    if not tga:
        return html
    # val+note 전체 블록: DTS Closing note 텍스트로 정확히 타겟팅
    note_pat = re.compile(r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov')
    m_note = note_pat.search(html)
    if not m_note:
        print(f"    ⚠️  미매칭: TGA")
        return html
    new_note = f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov'
    html = html[:m_note.start()] + new_note + html[m_note.end():]
    # val 교체: 새 note 앞 150자 안에서
    pos = html.find(new_note)
    segment = html[max(0, pos-150):pos]
    new_segment = re.sub(
        r'(>\$)[\d,.]+B(</td>)',
        lambda x: f'{x.group(1)}{tga["bal_b"]:,.1f}B{x.group(2)}',
        segment, count=1
    )
    html = html[:max(0, pos-150)] + new_segment + html[pos:]
    print(f"    ✅ TGA {tga['val_str']} ({tga['date']})")

    html = sub(html,
        r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov',
        f'{tga["date"]} DTS Closing {tga["val_str"]} · fiscaldata.treasury.gov',
        label="TGA note")
    # v17: "TGA threshold" 패치 제거. 앵커가 요구하던 "(전일" 문자열이 본문에
    #      존재하지 않아 오래전부터 사망 상태였고, threshold 서술은 수동 해설
    #      영역이므로 자동 패치 대상이 아니다(매번 미매칭 경고만 유발했음).
    register_anchor("TGA note",
        r'\d+/\d+ DTS Closing \$[\d,.]+B · fiscaldata\.treasury\.gov')
    return html


def patch_rrp(html, rrp):
    if not rrp:
        return html
    return _patch_val_by_note(
        html,
        r'\d+/\d+ · FRED RRPONTSYD [\d.]+B',
        f'{rrp["date"]} · FRED RRPONTSYD {rrp["val"]:.3f}B',
        r'(<td class="val val-ok">\$)[\d.]+B(</td>)',
        lambda m: f'{m.group(1)}{rrp["val"]:.2f}B{m.group(2)}',
        "RRP")


def patch_dgs10(html, dgs10):
    if not dgs10:
        return html
    return _patch_val_by_note(
        html,
        r'\d+/\d+ 종가 · FRED DGS10',
        f'{dgs10["date"]} 종가 · FRED DGS10',
        r'(<td class="val val-ok">)[\d.]+%(</td>)',
        lambda m: f'{m.group(1)}{dgs10["val"]:.2f}%{m.group(2)}',
        "DGS10")


def _repo_cls(bp):
    """v17.3 재보정: 임계가 GCF 기준(+20/+30bp)이라 SOFR-IORB에는 영원히 안 걸렸다.
    SOFR-IORB는 지준 풍부 시 음수가 정상이고 0 접근·역전이 희소화 신호다."""
    if bp >= 0:
        return "val-alert"
    if bp >= -5:
        return "val-warn"
    return "val-ok"


REPO_NOTE_RX = (r'(?:\d+/\d+ SOFR [\d.]+% vs IORB [\d.]+% · '
                r'(?:역전 해소|GCF 미공개로 SOFR-IORB 대체)'
                r'|<b style="color:#8B1A1A">값·지표 정의 불일치</b>[^<]*'
                r'(?:<[^>]+>[^<]*)*?표시값은 284bp)')


def patch_sofr(html, sofr, iorb=None):
    if not sofr:
        return html
    html = sub(html,
        r'(<td class="val val-ok">)([\d.]+%)(\ / [\d.]+%</td>)',
        lambda m: f'{m.group(1)}{sofr["val"]:.2f}%{m.group(3)}',
        label="SOFR val")
    html = sub(html,
        r'\d+/\d+ SOFR [\d.]+% · FRED 확인',
        f'{sofr["date"]} SOFR {sofr["val"]:.2f}% · FRED 확인',
        label="SOFR note")
    # v17: Repo Stress 행은 note만 갱신되고 val 패치가 아예 없어
    #      과거 수동 입력값(284bp)이 화석으로 남아 "값 284bp / 설명 -3bp" 모순 발생.
    #      GCF는 DTCC 미공개이므로 이 행의 값은 SOFR-IORB 대체치임을 명시하고 함께 패치한다.
    if iorb:
        iorb_val, iorb_src = iorb["val"], f'IORB {iorb["date"]}'
    else:
        iorb_val, iorb_src = IORB_FALLBACK, "IORB 폴백값(조회실패)"
        print(f'    \u26a0\ufe0f  IORB 조회 실패 → 폴백 {IORB_FALLBACK}% 사용 (스프레드 신뢰도 저하)')
    spread_bp = round((sofr["val"] - iorb_val) * 100)
    html = _patch_val_by_note(
        html,
        REPO_NOTE_RX,
        f'{sofr["date"]} SOFR {sofr["val"]:.2f}% vs IORB {iorb_val:.2f}% · GCF 미공개로 SOFR-IORB 대체',
        r'<td class="val[^"]*"[^>]*>.*?</td>',
        lambda m: f'<td class="val {_repo_cls(spread_bp)}">{spread_bp:+d}bp</td>',
        "Repo Stress val+note")
    register_anchor("Repo note", REPO_NOTE_RX)
    return html


def patch_auction(html, auction):
    if not auction:
        return html
    html = sub(html,
        r'(<td class="val val-(?:ok|warn)">)[\d.]+% \((?:30Y|10Y)\)(</td>)',
        f'\\g<1>{auction["ratio"]}% (10Y)\\g<2>',
        label="경매 val")
    html = sub(html,
        r'\d+Y \d+/\d+ 경매 · fiscaldata 확인',
        f'10Y {auction["date"]} 경매 · fiscaldata 확인',
        label="경매 note")
    return html


# v17: 읽기 앵커는 레거시 오염값("+-23K")까지 흡수하도록 [+-]{1,2} 로 완화하고,
#      쓰기는 {:+,} 단일 부호로 통일한다. 배지 색도 부호에 맞춰 조정.
NFP_VAL_RX  = r'(<td class="val val-(?:ok|warn|alert)">)\d+월: [+-]{1,2}[\d,]+K(</td>)'
NFP_NOTE_RX = r'\d+/\d+ 발표 · BLS \d+월 [+-]{1,2}[\d,]+K'


def patch_nfp(html, nfp):
    if not nfp:
        return html
    signed = nfp["signed"]          # 예: "-23K" / "+115K"
    month = nfp["month"]
    cls = "val-warn" if nfp["val"] < 0 else "val-ok"
    html = sub(html, NFP_VAL_RX,
        f'<td class="val {cls}">{month}: {signed}</td>',
        label="NFP val")
    html = sub(html, NFP_NOTE_RX,
        f'{nfp["date"]} 발표 · BLS {month} {signed}',
        label="NFP note")
    register_anchor("NFP val", NFP_VAL_RX)
    register_anchor("NFP note", NFP_NOTE_RX)
    return html


# v17: 이전 구현은 날짜만 바꾸고 "3월"을 하드코딩해 값을 전혀 쓰지 않았다.
#      Core YoY만 자동 갱신하고, 헤드라인 CPI는 FRED 단일 시리즈로 확정이
#      어려우므로 자동 대상에서 제외(수동 유지) — note에 그 사실을 명시한다.
# v17: note에 발표일을 포함시킨다. 날짜를 빼면 validate_patches가 미반영으로
#      경고하는데, 이를 예외 처리(skip)로 덮는 것이 과거 CPI 3개월 미갱신을
#      감춘 원인이었으므로 예외 대신 날짜를 넣는 방향으로 해결한다.
# v17.1: val 셀 전체를 헤드라인+Core로 완전히 재작성한다.
#        v17의 정규식은 'Core X%' 앞의 임의 텍스트를 [^<]* 로 먹어치워
#        수동 헤드라인 값을 조용히 삭제했다(실제 8/15 발생).
CPI_VAL_RX  = r'<td class="val val-(?:ok|warn|alert)">[^<]*Core [\d.]+%</td>'
CPI_NOTE_RX = (r'\d+/\d+ BLS \d+월 헤드라인 [\d.]+%·Core [\d.]+% · '
               r'FRED CPIAUCSL/CPILFESL 산출')


def patch_cpi(html, cpi):
    if not cpi:
        return html
    cls = "val-alert" if cpi["core"] >= 3.0 or cpi["headline"] >= 3.5 else "val-warn"
    html = sub(html, CPI_VAL_RX,
        f'<td class="val {cls}">헤드라인 {cpi["headline"]:.1f}% / Core {cpi["core"]:.1f}%</td>',
        label="CPI val")
    html = sub(html,
        r'(?:\d+/\d+ BLS \d+월 Core YoY [\d.]+% · FRED CPILFESL 산출\(헤드라인 수동\)'
        r'|\d+/\d+ BLS 발표 · \d+월 [^<]*'
        r'|' + CPI_NOTE_RX + r')',
        f'{cpi["date"]} BLS {cpi["month"]} 헤드라인 {cpi["headline"]:.1f}%·'
        f'Core {cpi["core"]:.1f}% · FRED CPIAUCSL/CPILFESL 산출',
        label="CPI note")
    register_anchor("CPI val", CPI_VAL_RX)
    register_anchor("CPI note", CPI_NOTE_RX)
    return html


UNRATE_NOTE_RX = r'\d+월 BLS · \d+/\d+ 발표(?: · [\d.]+%)?'


def patch_unrate(html, unrate):
    if not unrate:
        return html
    # v17: 기존 앵커는 "3월"을 하드코딩해 월이 바뀌면 못 읽었다(수동 정정 시 즉시 파손).
    #      월을 변수로 흡수하고, 쓰기 포맷도 동일 구조로 통일한다.
    register_anchor("실업률 note", UNRATE_NOTE_RX)
    return _patch_val_by_note(
        html,
        UNRATE_NOTE_RX,
        f'{unrate.get("month", "최신")} BLS · {unrate["date"]} 발표 · {unrate["val"]:.1f}%',
        r'(<td class="val val-(?:ok|warn|alert)">)[\d.]+%(</td>)',
        lambda m: f'{m.group(1)}{unrate["val"]:.1f}%{m.group(2)}',
        "실업률")


def patch_ci(html, ci):
    """v17: 자동 패치 공식 제외.
    FRED BUSLOANS는 월간 SA이고 monitor의 row-ci는 H.8 주간값 + 주체 분해 서술을
    수동 관리한다. 두 숫자는 개념이 달라 한 셀을 두고 충돌하므로, 자동 덮어쓰기는
    매주 H.8 분석을 월간값으로 파괴한다. 조회는 유지하되 참고 출력만 한다."""
    if not ci:
        return html
    print(f"    \u2139\ufe0f  C&I 자동패치 제외(H.8 수동 관리) — 참고: "
          f'FRED BUSLOANS {ci["val"]:,.1f}B ({ci["date"]})')
    return html


def patch_spx(html, spx):
    if not spx:
        return html
    return _patch_val_by_note(
        html,
        r'\d+/\d+ 종가 · FRED SP500',
        f'{spx["date"]} 종가 · FRED SP500',
        r'(<td class="val val-(?:ok|warn)">)[\d,]+\.?\d*(<br>(?:<br>)?</td>)',
        lambda m: f'{m.group(1)}{spx["val"]:,.2f}{m.group(2)}',
        "SPX")


def patch_vix(html, vix):
    if not vix:
        return html
    # val+note 전체 블록을 note anchor로 정확히 교체
    m = re.search(
        r'<td class="val val-(?:ok|warn)">[^<]+</td>\s*'
        r'<td class="verify"><span[^>]*>[^<]*</span>'
        r'<span class="verify-note">\d+/\d+ 종가 · FRED VIXCLS</span></td>',
        html
    )
    if not m:
        print(f"    ⚠️  미매칭: VIX")
        return html
    old_str = m.group(0)
    status = "val-warn" if vix["val"] >= 20 else "val-ok"
    new_str = (
        f'<td class="val {status}">{vix["val"]:.2f}</td>\n  '
        f'<td class="verify"><span class="vbadge vbadge-auto">자동확인</span>'
        f'<span class="verify-note">{vix["date"]} 종가 · FRED VIXCLS</span></td>'
    )
    html = html.replace(old_str, new_str, 1)
    print(f"    ✅ VIX {vix['val']:.2f} ({vix['date']})")
    return html


def patch_dxy(html, dxy):
    if not dxy:
        return html
    # 직접 교체 (초기) or 재업데이트
    old_ok = re.search(
        r'<td class="val val-(?:ok|warn)">[\d.]+</td>\s*'
        r'<td class="verify"><span class="vbadge [^"]+">[^<]+</span>'
        r'<span class="verify-note">\d+/\d+ 종가 · (?:Investing\.com|FRED DTWEXBGS)</span></td>',
        html
    )
    if old_ok:
        old_str = old_ok.group(0)
        new_str = re.sub(r'(>)[\d.]+(<\/td>)', f'\\g<1>{dxy["val"]:.2f}\\g<2>', old_str, count=1)
        new_str = re.sub(r'\d+/\d+ 종가 · (?:Investing\.com|FRED DTWEXBGS)',
                         f'{dxy["date"]} 종가 · FRED DTWEXBGS', new_str)
        new_str = new_str.replace('vbadge-ok">검색확인', 'vbadge-auto">자동확인')
        html = html.replace(old_str, new_str, 1)
        print(f"    ✅ DXY val+note")
    else:
        print(f"    ⚠️  미매칭: DXY")
    return html


def patch_cot(html, cot):
    if not cot:
        return html
    net_k = abs(cot["net"]) // 1000
    direction = cot["direction"]

    # COT 국채 val
    html = sub(html,
        r'(<td class="val val-(?:ok|warn)">)Net (?:Short|Long) [\d,]+K계약(</td>)',
        f'\\g<1>{direction} {net_k:,}K계약\\g<2>',
        label="COT val (국채)")
    html = sub(html,
        r'\d+/\d+ · CFTC TFF Lev Funds(?=</span></td>.*?구버전|</span></td>)',
        f'{cot["date"]} · CFTC TFF Lev Funds',
        label="COT note (국채)")

    # HF숏 val
    html = sub(html,
        r'(<td class="val val-(?:ok|warn)">~?)[\d,]+K계약(</td>)',
        f'\\g<1>{net_k:,}K계약\\g<2>',
        label="COT val (HF숏)")

    # 두 군데 배지 모두 자동확인으로
    html = sub(html,
        r'(<td class="verify">)<span class="vbadge [^"]+">[^<]+</span>'
        r'(<span class="verify-note">)\d+/\d+ · CFTC TFF Lev Funds',
        f'\\g<1>{AUTO_BADGE}\\g<2>{cot["date"]} · CFTC TFF Lev Funds',
        label="COT badge+note")
    return html


def patch_brent(html, brent):
    if not brent:
        return html
    html = _patch_val_by_note(
        html,
        r'\d+/\d+ 종가 · FRED DCOILBRENTEU',
        f'{brent["date"]} 종가 · FRED DCOILBRENTEU',
        r'(<td class="val val-(?:ok|warn|alert)">)\$?[\d.]+(\s*(?:/bbl)?</td>)',
        lambda m: f'{m.group(1)}${brent["val"]:.1f}{m.group(2)}',
        "Brent")
    # 배지 자동확인으로 업그레이드 (bounded regex 유지)
    html = sub(html,
        r'(<td class="verify">)<span class="vbadge [^"]+">[^<]+</span>'
        r'(<span class="verify-note">\d+/\d+ 종가 · FRED DCOILBRENTEU)',
        f'\\g<1>{AUTO_BADGE}\\g<2>',
        label="Brent badge")
    return html


def patch_wti(html, wti):
    if not wti:
        return html
    html = _patch_val_by_note(
        html,
        r'\d+/\d+ 종가 · FRED DCOILWTICO',
        f'{wti["date"]} 종가 · FRED DCOILWTICO',
        r'(<td class="val val-(?:ok|warn|alert)">)\$?[\d.]+(\s*(?:/bbl)?</td>)',
        lambda m: f'{m.group(1)}${wti["val"]:.1f}{m.group(2)}',
        "WTI")
    html = sub(html,
        r'(<td class="verify">)<span class="vbadge [^"]+">[^<]+</span>'
        r'(<span class="verify-note">\d+/\d+ 종가 · FRED DCOILWTICO)',
        f'\\g<1>{AUTO_BADGE}\\g<2>',
        label="WTI badge")
    return html


# ── 메인 패치 ────────────────────────────────────────────────────

def patch_ig_oas(html, ig):
    if not ig:
        return html
    bp = round(ig["val"] * 100)
    # note 텍스트로 먼저 찾아서 교체 — regex 충돌 방지
    note_pat = re.compile(r'FRED \d+/\d+ · [\d.]+% · BAMLC0A0CM')
    m_note = note_pat.search(html)
    if not m_note:
        print(f"    ⚠️  미매칭: IG OAS")
        return html
    new_note = f'FRED {ig["date"]} · {ig["val"]:.2f}% · BAMLC0A0CM'
    html = html[:m_note.start()] + new_note + html[m_note.end():]
    # val 교체: 새 note 앞에 있는 bp 값
    pos = html.find(new_note)
    segment = html[max(0, pos-150):pos]
    new_segment = re.sub(r'(>)\d+bp(</td>\s*$)', lambda x: f'{x.group(1)}{bp}bp{x.group(2)}', segment, count=1, flags=re.MULTILINE)
    html = html[:max(0, pos-150)] + new_segment + html[pos:]
    print(f"    ✅ IG OAS {bp}bp ({ig['date']})")
    return html

def patch_hy_oas(html, hy):
    if not hy:
        return html
    bp = round(hy["val"] * 100)
    note_pat = re.compile(r'FRED \d+/\d+ · [\d.]+% · BAMLH0A0HYM2')
    m_note = note_pat.search(html)
    if not m_note:
        print(f"    ⚠️  미매칭: HY OAS")
        return html
    new_note = f'FRED {hy["date"]} · {hy["val"]:.2f}% · BAMLH0A0HYM2'
    html = html[:m_note.start()] + new_note + html[m_note.end():]
    pos = html.find(new_note)
    segment = html[max(0, pos-150):pos]
    new_segment = re.sub(r'(>)\d+bp(</td>\s*$)', lambda x: f'{x.group(1)}{bp}bp{x.group(2)}', segment, count=1, flags=re.MULTILINE)
    html = html[:max(0, pos-150)] + new_segment + html[pos:]
    print(f"    ✅ HY OAS {bp}bp ({hy['date']})")
    return html

def patch_reserves(html, res):
    if not res:
        return html
    val_b = res["val"] / 1_000
    status = "val-warn" if val_b < 3000 else "val-ok"
    # val+note 직접 교체
    html = re.sub(
        r'(<td class="val val-(?:ok|warn)">)\$[\d,]+B(</td>\s*<td class="verify"><span[^>]*>[^<]*</span><span class="verify-note">\d+/\d+ · FRED WRBWFRBL</span></td>)',
        lambda m: f'<td class="val {status}">${val_b:,.0f}B' + m.group(2),
        html, count=1
    )
    html = sub(html,
        r'\d+/\d+ · FRED WRBWFRBL',
        f'{res["date"]} · FRED WRBWFRBL',
        label="지준 note")
    return html


def patch_walcl(html, walcl):
    if not walcl:
        return html
    val_b = walcl["val"] / 1_000
    html = re.sub(
        r'(<td class="val val-(?:ok|warn)">)\$[\d,]+B(</td>\s*<td class="verify"><span[^>]*>[^<]*</span><span class="verify-note">\d+/\d+ · FRED WALCL</span></td>)',
        lambda m: f'<td class="val val-ok">${val_b:,.0f}B' + m.group(2),
        html, count=1
    )
    html = sub(html,
        r'\d+/\d+ · FRED WALCL',
        f'{walcl["date"]} · FRED WALCL',
        label="WALCL note")
    return html


def patch_deposits(html, dep):
    if not dep:
        return html
    html = re.sub(
        r'(<td class="val val-(?:ok|warn)">)\$[\d,]+B(</td>\s*<td class="verify"><span[^>]*>[^<]*</span><span class="verify-note">\d+/\d+ · FRED DPSACBW027SBOG</span></td>)',
        lambda m: f'<td class="val val-ok">${dep["val"]:,.0f}B' + m.group(2),
        html, count=1
    )
    html = sub(html,
        r'\d+/\d+ · FRED DPSACBW027SBOG',
        f'{dep["date"]} · FRED DPSACBW027SBOG',
        label="예금 note")
    return html


def patch_usdjpy(html, usdjpy):
    if not usdjpy:
        return html
    m = re.search(
        r'<td class="val val-(?:ok|warn|alert)">[\d.]+</td>\s*'
        r'<td class="verify"><span[^>]*>[^<]*</span>'
        r'<span class="verify-note">\d+/\d+ 종가 · FRED DEXJPUS</span></td>',
        html
    )
    if m:
        old = m.group(0)
        new = re.sub(r'(>)[\d.]+(</td>\s*<td class="verify">)', lambda x: f'{x.group(1)}{usdjpy["val"]:.2f}{x.group(2)}', old, count=1)
        new = re.sub(r'\d+/\d+ 종가 · FRED DEXJPUS', f'{usdjpy["date"]} 종가 · FRED DEXJPUS', new)
        new = new.replace('vbadge-ok">검색확인', 'vbadge-auto">자동확인')
        html = html.replace(old, new, 1)
        print(f"    ✅ USD/JPY {usdjpy['val']:.2f} ({usdjpy['date']})")
    else:
        print(f"    ⚠️  미매칭: USD/JPY")
    return html


def patch_stlfsi(html, stlfsi):
    if not stlfsi:
        return html
    # note anchor로 정확히 1건만 교체
    m = re.search(
        r'<td class="val val-(?:ok|warn)">[^<]+</td>\s*'
        r'<td class="verify"><span[^>]*>[^<]*</span>'
        r'<span class="verify-note">\d+/\d+ · FRED STLFSI4</span></td>',
        html
    )
    if not m:
        print(f"    ⚠️  미매칭: STLFSI4")
        return html
    old_str = m.group(0)
    new_str = (
        f'<td class="val val-ok">{stlfsi["val"]:.3f}</td>\n  '
        f'<td class="verify"><span class="vbadge vbadge-auto">자동확인</span>'
        f'<span class="verify-note">{stlfsi["date"]} · FRED STLFSI4</span></td>'
    )
    html = html.replace(old_str, new_str, 1)
    print(f"    ✅ STLFSI4 {stlfsi['val']:.3f} ({stlfsi['date']})")
    return html


# v17: 이전 앵커는 'Q\d 20\d\d · FHLB' 인데 쓰는 값은 '· FRED Z.1 (...)' 이라
#      자기가 쓴 결과를 자기 앵커가 못 읽는 자기 오염 → 1회만 성공하고 영구 실패.
#      읽기 앵커를 실제 쓰기 포맷과 일치시키고, 레거시 형태도 함께 흡수한다.
# v17.3: 공식 CFR 수치를 병기하는 형식으로 통일(수동 편집분까지 흡수).
#        FRED Z.1과 공식 CFR은 약 $10B 상시 차이 → 둘 다 남겨야 오독이 없다.
FHLB_NOTE_RX = (r'Q\d 20\d\d · FRED Z\.1 \$[\d,.]+B / <b>공식 CFR [^<]*</b>[^<]*'
                r'|Q\d 20\d\d · (?:FRED Z\.1 \(FHLB 공식[^)]*\)|FHLB[^<]*)')


def patch_fhlb(html, fhlb):
    if not fhlb:
        return html
    val_b = fhlb["val"] / 1_000
    m = re.search(
        r'<td class="val val-(?:ok|warn|alert)">[^<]+</td>\s*'
        r'<td class="verify"><span[^>]*>[^<]*</span>'
        r'<span class="verify-note">' + FHLB_NOTE_RX,
        html
    )
    if not m:
        print(f"    \u26a0\ufe0f  미매칭: FHLB")
        return html

    old_str = m.group(0)
    # 임계($700B) 초과 여부에 따라 색상 클래스 조정
    # v17.3: 레벨 단독으로 경보 색을 주지 않는다(Q2 2025 $742.8B 선례 확인).
    #        경보는 「$700B + 연체발생 + H.8 소형은행 Borrowings 증가」 3요건 수동 판정.
    cls = "val-warn" if val_b >= 700 else "val-ok"
    new_str = re.sub(
        r'<td class="val val-(?:ok|warn|alert)">[^<]+</td>',
        f'<td class="val {cls}">${val_b:,.1f}B</td>',
        old_str, count=1
    )
    new_str = re.sub(
        FHLB_NOTE_RX,
        f'{fhlb.get("quarter","Q?")} {fhlb.get("year","?")} · FRED Z.1 ${val_b:,.1f}B / '
        f'<b>공식 CFR $734.3B</b> — 공식 수치는 분기 CFR 발행 시 수동 갱신',
        new_str, count=1
    )
    new_str = new_str.replace('vbadge-ok">검색확인', 'vbadge-auto">자동확인')
    html = html.replace(old_str, new_str, 1)
    register_anchor("FHLB note", FHLB_NOTE_RX)
    flag = "  \U0001F7E1 $700B 초과(단독으로는 경보 아님·3요건 확인 필요)" if val_b >= 700 else ""
    print(f"    \u2705 FHLB ${val_b:,.1f}B ({fhlb['date']}){flag}")
    return html


def validate_patches(html, data):
    """패치 후 날짜 기준 누락 의심 체크.
    v17: skip={"cpi","ci"} 예외 제거. 이 예외가 3개월간 CPI 미갱신을 조용히
    감췄다. 자동 패치 대상이 아닌 항목은 예외가 아니라 NO_PATCH로 명시한다."""
    NO_PATCH = {"ci"}          # 의도적 비패치(H.8 수동 관리)
    missing = []
    for key, val in data.items():
        if not val or key in NO_PATCH:
            continue
        date = val.get("date", "")
        if date and date not in html:
            missing.append(f"{key}({date})")
    if missing:
        print(f"  \u26a0\ufe0f  패치 후 날짜 미반영 의심: {', '.join(missing)}")
    else:
        print(f"  \u2705 패치 검증 OK")
    verify_anchors(html)


def patch_html(html, data):
    print("\n  [패치 시작]")
    html = patch_tga(html,     data.get("tga"))
    html = patch_rrp(html,     data.get("rrp"))
    html = patch_dgs10(html,   data.get("dgs10"))
    html = patch_sofr(html,    data.get("sofr"), data.get("iorb"))
    html = patch_auction(html, data.get("auction"))
    html = patch_nfp(html,     data.get("nfp"))
    html = patch_cpi(html,     data.get("cpi"))
    html = patch_unrate(html,  data.get("unrate"))
    html = patch_ci(html,      data.get("ci"))
    html = patch_spx(html,     data.get("spx"))
    html = patch_vix(html,     data.get("vix"))
    html = patch_dxy(html,     data.get("dxy"))
    html = patch_cot(html,     data.get("cot"))
    html = patch_brent(html,   data.get("brent"))
    html = patch_wti(html,     data.get("wti"))
    html = patch_ig_oas(html,  data.get("ig_oas"))
    html = patch_hy_oas(html,  data.get("hy_oas"))
    html = patch_reserves(html, data.get("reserves"))
    html = patch_walcl(html,    data.get("walcl"))
    html = patch_deposits(html,  data.get("deposits"))
    html = patch_fhlb(html,      data.get("fhlb"))
    html = patch_usdjpy(html,   data.get("usdjpy"))
    html = patch_stlfsi(html,   data.get("stlfsi"))
    return html


# ── Main ─────────────────────────────────────────────────────────

def preflight():
    """v17.2: main()이 참조하는 fetcher 이름이 전부 존재하는지 네트워크 호출 전에 확인.
    v17.1에서 리팩터링 중 fetch_unrate가 삭제됐는데, py_compile은 통과하고
    patch 단계만 mock으로 테스트해 배포 후에야 NameError로 터졌다.
    이름 해석 실패는 조회를 시작하기 전에 잡아야 한다."""
    required = [
        "fetch_tga", "fetch_fred", "fetch_nfp", "fetch_cpi", "fetch_unrate",
        "fetch_auction", "fetch_cot_ust10y", "fetch_oil", "fetch_oas", "fetch_iorb",
        "fetch_reserves", "fetch_walcl", "fetch_deposits", "fetch_fhlb",
        "fetch_usdjpy", "fetch_stlfsi", "_yoy_from_fred",
    ]
    g = globals()
    missing = [n for n in required if not callable(g.get(n))]
    if missing:
        print(f"  \U0001F534 preflight 실패 — 정의되지 않은 함수: {', '.join(missing)}")
        raise SystemExit(1)
    print(f"  \u2705 preflight OK ({len(required)}개 fetcher 확인)")


def main():
    # 버전을 먼저 찍는다. 로그 첫 줄만 보면 어느 버전이 도는지 즉시 확인 가능
    # (v16이 남아 있는데 v17로 착각해 오진하는 일을 방지)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] fetch_data {SCRIPT_VERSION} 시작\n")
    preflight()

    data = {}
    data["tga"]     = safe_fetch("TGA",     fetch_tga)
    data["dgs10"]   = safe_fetch("DGS10",   lambda: fetch_fred("DGS10"))
    data["sofr"]    = safe_fetch("SOFR",    lambda: fetch_fred("SOFR"))
    data["iorb"]    = safe_fetch("IORB",    fetch_iorb)
    data["rrp"]     = safe_fetch("RRP",     lambda: fetch_fred("RRPONTSYD"))
    data["nfp"]     = safe_fetch("NFP",     fetch_nfp)
    data["cpi"]     = safe_fetch("CPI",     fetch_cpi)
    data["unrate"]  = safe_fetch("UNRATE",  fetch_unrate)
    data["ci"]      = safe_fetch("C&I",     lambda: fetch_fred("BUSLOANS"))
    data["auction"] = safe_fetch("경매IB",  fetch_auction)
    data["spx"]     = safe_fetch("S&P500",  lambda: fetch_fred("SP500"))
    data["vix"]     = safe_fetch("VIX",     lambda: fetch_fred("VIXCLS"))
    data["dxy"]     = safe_fetch("DXY",     lambda: fetch_fred("DTWEXBGS"))
    data["cot"]     = safe_fetch("COT_UST", fetch_cot_ust10y)
    data["brent"]   = safe_fetch("Brent",   lambda: fetch_oil("DCOILBRENTEU"))
    data["wti"]     = safe_fetch("WTI",     lambda: fetch_oil("DCOILWTICO"))
    data["ig_oas"]  = safe_fetch("IG OAS",  lambda: fetch_oas("BAMLC0A0CM"))
    data["hy_oas"]  = safe_fetch("HY OAS",  lambda: fetch_oas("BAMLH0A0HYM2"))
    data["reserves"] = safe_fetch("지준",     fetch_reserves)
    data["walcl"]    = safe_fetch("WALCL",    fetch_walcl)
    data["deposits"] = safe_fetch("예금",     fetch_deposits)
    data["fhlb"]     = safe_fetch("FHLB",     fetch_fhlb)
    data["usdjpy"]   = safe_fetch("USD/JPY",  fetch_usdjpy)
    data["stlfsi"]   = safe_fetch("STLFSI4",  fetch_stlfsi)

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
