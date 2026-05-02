import os
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig", override=True)

BASE_URL  = os.getenv("SITE_BASE_URL", "http://www.naesonda.com")
SITE_ID   = os.getenv("SITE_ID")
SITE_PW   = os.getenv("SITE_PW")
ID_FIELD  = os.getenv("SITE_ID_FIELD", "mb_id")
PW_FIELD  = os.getenv("SITE_PW_FIELD", "mb_pass")
SAVE_DIR  = "docs"

TARGET_PAGES = [
    "http://www.naesonda.com/bbs/board.php?tbl=bbs41",
    "http://www.naesonda.com/bbs/board.php?tbl=bbs42",
    "http://www.naesonda.com/bbs/board.php?tbl=bbs44",
    "http://www.naesonda.com/bbs/board.php?tbl=bbs31",
    "http://www.naesonda.com/bbs/board.php?tbl=bbs32",
]

LOGIN_PAGE = "http://www.naesonda.com/member/login.php"

def get_soup(resp):
    resp.encoding = "euc-kr"
    return BeautifulSoup(resp.text, "html.parser")

def login():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    # 로그인 페이지 접속 → 숨겨진 필드 값 수집
    resp = session.get(LOGIN_PAGE)
    soup = get_soup(resp)

    payload = {}
    for inp in soup.find_all("input"):
        name = inp.get("name")
        value = inp.get("value", "")
        if name:
            payload[name] = value

    # 아이디/비밀번호 설정 (EUC-KR 인코딩)
    payload[ID_FIELD] = SITE_ID
    payload[PW_FIELD] = SITE_PW

    # 로그인 요청
    resp = session.post(LOGIN_PAGE, data=payload, allow_redirects=True)
    resp.encoding = "euc-kr"

    # 로그인 성공 여부 확인 (로그인 메뉴가 사라지면 성공)
    soup = get_soup(resp)
    login_link = soup.find("a", href=lambda h: h and "login.php" in h)
    if login_link:
        print("로그인 실패 - 아이디/비밀번호를 확인하세요")
    else:
        print("로그인 성공")

    return session

def get_post_links(session, board_url):
    post_links = []
    page = 1
    tbl = parse_qs(urlparse(board_url).query).get("tbl", [""])[0]

    while True:
        paged_url = f"{board_url}&page={page}"
        resp = session.get(paged_url)
        soup = get_soup(resp)

        links_on_page = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # 게시글 링크 패턴: mode=VIEW&num= 형태
            if tbl in href and "mode=VIEW" in href and "num=" in href:
                full = urljoin(BASE_URL, href)
                if full not in post_links and full not in links_on_page:
                    links_on_page.append(full)

        if not links_on_page:
            break

        post_links.extend(links_on_page)
        print(f"  페이지 {page}: {len(links_on_page)}개 게시글")

        # 다음 페이지 링크 확인
        has_next = any(
            f"page={page+1}" in a["href"]
            for a in soup.find_all("a", href=True)
            if tbl in a["href"]
        )
        if not has_next:
            break

        page += 1
        time.sleep(0.5)

    return post_links

def get_pdf_links_from_post(session, post_url):
    resp = session.get(post_url)
    soup = get_soup(resp)
    pdf_links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(BASE_URL, href)
        if ".pdf" in href.lower() or "download" in href.lower() or "file" in href.lower():
            if full not in pdf_links:
                pdf_links.append(full)

    return pdf_links

def download_pdf(session, url, referer="", board_name=""):
    try:
        headers = {"Referer": referer} if referer else {}
        resp = session.get(url, headers=headers, stream=True, timeout=30)

        # Content-Type이 HTML이면 다운로드 실패
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            return

        # 파일명 추출 (EUC-KR/CP949 디코딩)
        filename = ""
        cd = resp.headers.get("Content-Disposition", "")
        if "filename=" in cd:
            raw = cd.split("filename=")[-1].strip().strip('"').strip("'")
            for enc in ("cp949", "euc-kr", "utf-8"):
                try:
                    filename = raw.encode("latin-1").decode(enc)
                    break
                except Exception:
                    continue

        # 파일명 추출 실패 시 URL의 no= 값으로 대체
        if not filename or filename == "download.php":
            no = parse_qs(urlparse(url).query).get("no", ["unknown"])[0]
            filename = f"file_{no}.pdf"

        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        if board_name:
            filename = f"{board_name}_{filename}"

        # 파일명에 사용할 수 없는 문자 제거
        for ch in r'\/:*?"<>|':
            filename = filename.replace(ch, "_")

        save_path = os.path.join(SAVE_DIR, filename)
        if os.path.exists(save_path):
            print(f"  이미 존재: {filename}")
            return

        if resp.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(1024):
                    f.write(chunk)
            print(f"  다운로드: {filename}")
        else:
            print(f"  실패({resp.status_code}): {url}")
    except Exception as e:
        print(f"  오류: {e}")

def crawl():
    session = login()
    total_pdfs = 0

    for board_url in TARGET_PAGES:
        board_name = parse_qs(urlparse(board_url).query).get("tbl", [""])[0]
        print(f"\n[ 게시판: {board_name} ] {board_url}")

        post_links = get_post_links(session, board_url)
        print(f"  총 게시글: {len(post_links)}개")

        for post_url in post_links:
            pdf_links = get_pdf_links_from_post(session, post_url)
            for pdf_url in pdf_links:
                download_pdf(session, pdf_url, referer=post_url, board_name=board_name)
                total_pdfs += 1
            time.sleep(0.3)

    print(f"\n크롤링 완료! 총 {total_pdfs}개 PDF 처리")

if __name__ == "__main__":
    if not SITE_ID or not SITE_PW:
        print("ERROR: .env 파일에 SITE_ID와 SITE_PW를 설정해 주세요.")
    else:
        crawl()
