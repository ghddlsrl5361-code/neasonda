import os
import json
import pdfplumber
import pytesseract
import fitz  # pymupdf
from PIL import Image
import io

# Tesseract 설치 경로 직접 지정
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

DOCS_DIR   = "docs"
INDEX_FILE = "doc_index.json"
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 100

def extract_text_pdfplumber(pdf_path):
    """텍스트 기반 PDF에서 직접 추출"""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass
    return text.strip()

def extract_text_ocr(pdf_path):
    """스캔 이미지 PDF에서 OCR로 추출"""
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            # PDF 페이지를 이미지로 변환 (300dpi)
            mat = fitz.Matrix(300/72, 300/72)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            # 한국어 OCR
            page_text = pytesseract.image_to_string(img, lang="kor+eng")
            if page_text.strip():
                text += page_text + "\n"
        doc.close()
    except Exception as e:
        print(f"  OCR 오류: {e}")
    return text.strip()

def extract_text(pdf_path):
    """텍스트 추출 시도 → 실패 시 OCR로 전환"""
    text = extract_text_pdfplumber(pdf_path)
    if text and len(text) > 50:
        return text, "직접추출"
    text = extract_text_ocr(pdf_path)
    if text and len(text) > 50:
        return text, "OCR"
    return "", "실패"

def split_into_chunks(text, source):
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i:i + CHUNK_SIZE].strip()
        if chunk:
            chunks.append({"text": chunk, "source": source})
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks

def build_index():
    pdf_files = [f for f in os.listdir(DOCS_DIR) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print("docs 폴더에 PDF 파일이 없습니다.")
        return

    all_chunks = []
    success, ocr_success, failed = 0, 0, 0

    for pdf_file in pdf_files:
        print(f"처리 중: {pdf_file}", end="  ")
        text, method = extract_text(os.path.join(DOCS_DIR, pdf_file))
        if text:
            chunks = split_into_chunks(text, pdf_file)
            all_chunks.extend(chunks)
            print(f"→ {method} ({len(chunks)}개 단락)")
            if method == "OCR":
                ocr_success += 1
            else:
                success += 1
        else:
            print("→ 추출 실패")
            failed += 1

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"\n인덱싱 완료!")
    print(f"  직접추출: {success}개 / OCR: {ocr_success}개 / 실패: {failed}개")
    print(f"  총 {len(all_chunks)}개 단락 → {INDEX_FILE}")

if __name__ == "__main__":
    build_index()
