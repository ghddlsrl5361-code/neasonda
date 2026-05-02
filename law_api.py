import os
import re
import json
import requests
from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig", override=True)

def _get_secret(key):
    try:
        import streamlit as st
        return st.secrets[key]
    except Exception:
        return os.getenv(key)

API_KEY   = _get_secret("LAW_API_KEY")
BASE_URL  = "http://www.law.go.kr/DRF"
CACHE_FILE = "law_mst_cache.json"

# 재개발 사업 관련 주요 법령 목록
MAJOR_LAWS = [
    "도시 및 주거환경정비법",
    "도시 및 주거환경정비법 시행령",
    "집합건물의 소유 및 관리에 관한 법률",
    "주택법",
    "상법",
    "건설산업기본법",
    "건축법",
    "부동산등기법",
    "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률",
]

def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", str(text)).strip()

def get_law_mst(law_name: str) -> str | None:
    """법령명으로 MST 번호 조회"""
    try:
        resp = requests.get(f"{BASE_URL}/lawSearch.do", params={
            "OC": API_KEY, "target": "law", "type": "JSON",
            "query": law_name, "display": 3, "sort": "efYd",
        }, timeout=10)
        laws = resp.json().get("LawSearch", {}).get("law", [])
        if isinstance(laws, dict):
            laws = [laws]
        # 법령명이 정확히 일치하는 것 우선
        for law in laws:
            name = law.get("법령명한글", "")
            if law_name in name or name in law_name:
                return law.get("법령일련번호")
        return laws[0].get("법령일련번호") if laws else None
    except Exception:
        return None

def load_or_build_cache() -> dict:
    """주요 법령 MST 캐시 로드 (없으면 API로 조회 후 저장)"""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    print("주요 법령 MST 캐시를 구성 중입니다 (최초 1회)...")
    cache = {}
    for law_name in MAJOR_LAWS:
        mst = get_law_mst(law_name)
        if mst:
            cache[law_name] = mst
            print(f"  {law_name}: MST={mst}")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print("캐시 저장 완료\n")
    return cache

def search_articles_in_law(mst: str, keyword: str, max_results: int = 3) -> list[str]:
    """법령 조문에서 키워드 포함 조문 검색"""
    try:
        resp = requests.get(f"{BASE_URL}/lawService.do", params={
            "OC": API_KEY, "target": "law", "MST": mst, "type": "JSON",
        }, timeout=10)
        units = resp.json().get("법령", {}).get("조문", {}).get("조문단위", [])
        if isinstance(units, dict):
            units = [units]

        results = []
        for unit in units:
            if unit.get("조문여부") == "전문":
                continue
            unit_str = str(unit)
            if keyword not in unit_str:
                continue

            jo_num = unit.get("조문번호", "")
            lines  = [f"제{jo_num}조"]

            jo_body = unit.get("조문내용", "").strip()
            if jo_body:
                lines.append(f"  {strip_html(jo_body)[:200]}")

            hangs = unit.get("항", [])
            if isinstance(hangs, dict):
                hangs = [hangs]
            for hang in hangs:
                h_body = hang.get("항내용", "").strip()
                if h_body and keyword in h_body:
                    lines.append(f"  {strip_html(h_body)[:200]}")

            text = "\n".join(lines)
            if len(text) > 10:
                results.append(text)
            if len(results) >= max_results:
                break

        return results
    except Exception:
        return []

def search_laws(query: str) -> list[dict]:
    """주요 법령에서 질문 키워드 관련 조문 검색"""
    cache = load_or_build_cache()
    results = []

    # 핵심 키워드 추출 (2글자 이상 단어)
    keywords = [w for w in query.split() if len(w) >= 2]
    if not keywords:
        keywords = [query]

    for law_name, mst in cache.items():
        for keyword in keywords:
            articles = search_articles_in_law(mst, keyword)
            if articles:
                results.append({
                    "법령명": law_name,
                    "내용": "\n".join(articles),
                })
                break  # 법령당 하나의 키워드면 충분

    return results[:3]  # 최대 3개 법령

def search_precedents(query: str, display: int = 3) -> list[dict]:
    """판례 검색"""
    try:
        # 핵심 단어 1~2개로 검색 (긴 문장은 결과 없음)
        keyword = query.split()[0] if query.split() else query

        resp = requests.get(f"{BASE_URL}/lawSearch.do", params={
            "OC": API_KEY, "target": "prec", "type": "JSON",
            "query": keyword, "display": display,
            "sort": "ddes", "section": "all",
        }, timeout=10)
        data = resp.json()
        search = data.get("PrecSearch", {})

        if int(search.get("totalCnt", 0)) == 0:
            return []

        precs = search.get("prec", [])
        if isinstance(precs, dict):
            precs = [precs]

        results = []
        for p in precs:
            prec_id   = p.get("판례일련번호", "")
            case_name = p.get("사건명", "")
            case_no   = p.get("사건번호", "")
            court     = p.get("법원명", "")
            date      = p.get("선고일자", "")

            detail  = get_precedent_detail(prec_id) if prec_id else ""
            summary = detail or case_name

            if summary:
                results.append({
                    "사건명": case_name,
                    "사건번호": f"{court} {date} {case_no}".strip(),
                    "요지": summary,
                })
        return results
    except Exception as e:
        print(f"[판례 검색 오류] {e}")
        return []

def get_precedent_detail(prec_id: str) -> str:
    """판례 상세(판결요지) 조회"""
    try:
        resp = requests.get(f"{BASE_URL}/lawService.do", params={
            "OC": API_KEY, "target": "prec", "ID": prec_id, "type": "JSON",
        }, timeout=10)
        prec = resp.json().get("PrecService", {})
        summary = prec.get("판결요지") or prec.get("판시사항") or ""
        return strip_html(str(summary))[:400] if summary else ""
    except Exception:
        return ""

def build_legal_context(query: str) -> str:
    """질문에 대한 법령 + 판례 컨텍스트 생성"""
    parts = []

    laws = search_laws(query)
    if laws:
        parts.append("【관련 법령】")
        for law in laws:
            parts.append(f"■ {law['법령명']}\n{law['내용']}")

    precs = search_precedents(query)
    if precs:
        parts.append("\n【관련 판례】")
        for p in precs:
            parts.append(f"■ {p['사건명']}\n({p['사건번호']})\n{p['요지']}")

    return "\n".join(parts)
