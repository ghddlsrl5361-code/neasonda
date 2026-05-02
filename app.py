import os
import re
import json
import streamlit as st
from groq import Groq
from dotenv import load_dotenv
from law_api import build_legal_context

load_dotenv(encoding="utf-8-sig", override=True)

# 로컬: .env 파일 / Streamlit Cloud: st.secrets 자동 사용
def get_secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key)

client = Groq(api_key=get_secret("GROQ_API_KEY"))

with open("policy.txt", "r", encoding="utf-8") as f:
    POLICY_DATA = f.read()

# BM25 문서 검색 초기화
USE_DOCS = False
bm25 = None
doc_chunks = []

if os.path.exists("doc_index.json"):
    try:
        from rank_bm25 import BM25Okapi
        with open("doc_index.json", "r", encoding="utf-8") as f:
            doc_chunks = json.load(f)
        tokenized = [c["text"].split() for c in doc_chunks]
        bm25 = BM25Okapi(tokenized)
        USE_DOCS = True
    except Exception as e:
        print(f"문서 인덱스 로딩 실패: {e}")

def clean_response(text: str) -> str:
    """응답에서 한자·외국어 제거 후 자연스러운 한국어로 정리"""
    # 한자 범위 제거 (CJK 통합 한자)
    text = re.sub(r'[一-鿿㐀-䶿]+', '', text)
    # 아랍 문자, 태국어, 베트남어 특수 발음 부호 등 제거
    text = re.sub(r'[؀-ۿ฀-๿Ḁ-ỿ]', '', text)
    # 연속 공백/빈 줄 정리
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def search_docs(query: str, n: int = 3) -> str:
    if not bm25 or not doc_chunks:
        return ""
    tokens = query.split()
    scores = bm25.get_scores(tokens)
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]
    results = []
    for i in top_indices:
        if scores[i] > 0:
            chunk = doc_chunks[i]
            results.append(f"[출처: {chunk['source']}]\n{chunk['text']}")
    return "\n\n".join(results)

SYSTEM_PROMPT = f"""[절대 규칙] 모든 답변은 반드시 순수한 한국어(한글)로만 작성하세요.
- 한자(漢字) 사용 금지: 公平, 信任, 重要 등 한자어를 한자로 쓰지 말고 반드시 한글로만 쓰세요.
- 영어 사용 금지: wichtige, important, key 등 영어 단어를 섞지 마세요.
- 기타 외국어(중국어, 일본어, 베트남어 등) 사용 금지.
- 참고 문서에 한자나 외국어가 있어도 답변은 반드시 순수 한국어로만 작성하세요.
- 위 규칙을 어기면 답변 전체를 다시 작성하세요.

당신은 조합장 선거에서 박은성 후보를 지지하는 조합원의 입장에서
다른 조합원들의 질문이나 의견에 답변하는 AI 어시스턴트입니다.

아래는 박은성 후보의 정책과 입장 자료입니다:

{POLICY_DATA}

답변 원칙:
1. 정책 질문: 위 자료를 바탕으로 명확하고 친절하게 설명하세요.
2. 비례율/공사비 관련 우려: 수치 논쟁보다 실질적 이익(빠른 등기, 사업 완료)을 강조하세요.
3. 전 조합장 관련 루머나 비난: "사실과 루머를 구분해야 한다"는 입장을 유지하고,
   지금은 사업 완료가 우선이라는 방향으로 대화를 돌리세요.
4. 원색적 비난이나 감정적 공격: 흥분하지 않고 품위 있게 반박하되,
   핵심 사실(소송 → 계좌 동결 → 사업 중단)로 논점을 되돌리세요.
5. 연제동 후보 지지 의견: 상대 후보를 인신공격하지 말고,
   정책의 실현 가능성 차이를 사실 기반으로 설명하세요.
6. 관련 법령이나 조합 문서가 제공된 경우 이를 근거로 답변하고 출처를 명시하세요.
7. 답변은 간결하게 3~5문장 내외로 작성하고, 필요시 핵심만 bullet point로 정리하세요.
8. 반드시 순수 한국어(한글)로만 답변하세요. 한자·영어·외국어는 단 한 글자도 사용하지 마세요.
9. 조합원을 설득하는 어조이되, 강압적이거나 선동적이지 않게 하세요.

[최종 확인] 답변 작성 후 한자나 외국어가 없는지 반드시 검토하고, 있으면 한국어로 바꾸세요.
"""

st.set_page_config(page_title="조합장 선거 Q&A", page_icon="🏗️", layout="centered")
st.title("🏗️ 박은성 후보 지지 Q&A")
st.caption("조합원들의 질문과 의견에 답변하는 자동 응답 시스템")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("질문이나 의견을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            doc_context   = search_docs(prompt)
            legal_context = build_legal_context(prompt)

            system = SYSTEM_PROMPT
            if doc_context:
                system += f"\n\n【조합 문서 참고 자료】\n{doc_context}"
            if legal_context:
                system += f"\n\n{legal_context}"

            api_messages = [{"role": "system", "content": system}] + [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
            ]
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=api_messages,
                max_tokens=1024,
            )
            answer = clean_response(response.choices[0].message.content)
            st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})

with st.sidebar:
    st.header("메뉴")
    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    if USE_DOCS:
        st.success(f"문서 검색 활성화\n({len(doc_chunks)}개 단락)")
    else:
        st.warning("문서 미등록\nindexer.py 실행 후 재시작")
    st.divider()
    st.caption("이 시스템은 박은성 후보 지지 입장에서 답변합니다.")
    st.caption("답변 내용은 참고용이며, 중요한 사안은 직접 확인하세요.")
