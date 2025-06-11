import os
import re
import sys
import base64
import tempfile
import subprocess
import webbrowser
import platform
import fitz  # PyMuPDF
import pandas as pd
import streamlit as st
import ast
from history_manager import get_customer_options

from ltv_map import region_map
from datetime import datetime
from history_manager import (
    load_customer_input,
    save_user_input,
    delete_customer_from_notion,
    get_customer_options,
)
# ─────────────────────────────
# 🏠 상단 타이틀 + 고객 이력 불러오기
# ─────────────────────────────

# ✅ 페이지 설정 (페이지 탭 고객명 + 아이콘)
st.set_page_config(
    page_title="LTV 계산기",
    page_icon="📊",  # 또는 💰, 🧮, 🏦 등 원하는 이모지 가능
    layout="wide",  # ← 화면 전체 너비로 UI 확장
    initial_sidebar_state="auto"
)

# ------------------------------
# 🔹 텍스트 기반 추출 함수들
# ------------------------------

def extract_address(text):
    m = re.search(r"\[집합건물\]\s*([^\n]+)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"소재지\s*[:：]?\s*([^\n]+)", text)
    if m:
        return m.group(1).strip()
    return ""

def extract_area_floor(text):
    m = re.findall(r"(\d+\.\d+)\s*㎡", text.replace('\n', ' '))
    area = f"{m[-1]}㎡" if m else ""
    floor = None
    addr = extract_address(text)
    f_match = re.findall(r"제(\d+)층", addr)
    if f_match:
        floor = int(f_match[-1])
    return area, floor

def extract_all_names_and_births(text):
    start = text.find("주요 등기사항 요약")
    if start == -1:
        return []
    summary = text[start:]
    lines = [l.strip() for l in summary.splitlines() if l.strip()]
    result = []
    for i in range(len(lines)):
        if re.match(r"[가-힣]+ \(공유자\)|[가-힣]+ \(소유자\)", lines[i]):
            name = re.match(r"([가-힣]+)", lines[i]).group(1)
            if i + 1 < len(lines):
                birth_match = re.match(r"(\d{6})-", lines[i + 1])
                if birth_match:
                    birth = birth_match.group(1)
                    result.append((name, birth))
    return result

# ------------------------------
# 🔹 PDF 처리 함수
# ------------------------------

def process_pdf(uploaded_file):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    text = ""
    external_links = []

    for page in doc:
        text += page.get_text("text")
        links = page.get_links()
        for link in links:
            if "uri" in link:
                external_links.append(link["uri"])

    doc.close()

    address = extract_address(text)
    area, floor = extract_area_floor(text)
    co_owners = extract_all_names_and_births(text)

    return text, external_links, address, area, floor, co_owners

# ------------------------------
# 🔹 유틸 함수
# ------------------------------

def floor_to_unit(value, unit=100):
    return value // unit * unit

def pdf_to_image(pdf_path, page_num, zoom=2.0):
    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        return None
    page = doc.load_page(page_num)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def format_with_comma(key):
    raw = st.session_state.get(key, "")
    clean = re.sub(r"[^\d]", "", raw)
    if clean.isdigit():
        st.session_state[key] = "{:,}".format(int(clean))
    else:
        st.session_state[key] = ""

def parse_korean_number(text: str) -> int:
    txt = text.replace(",", "").strip()
    total = 0
    m = re.search(r"(\d+)\s*억", txt)
    if m:
        total += int(m.group(1)) * 10000
    m = re.search(r"(\d+)\s*천만", txt)
    if m:
        total += int(m.group(1)) * 1000
    m = re.search(r"(\d+)\s*만", txt)
    if m:
        total += int(m.group(1))
    if total == 0:
        try:
            total = int(txt)
        except:
            total = 0
    return total

def format_kb_price():
    raw = st.session_state.get("raw_price_input", "")
    clean = parse_korean_number(raw)
    st.session_state["raw_price"] = "{:,}".format(clean) if clean else ""

def format_area():
    raw = st.session_state.get("area_input", "")
    clean = re.sub(r"[^\d.]", "", raw)
    st.session_state["extracted_area"] = f"{clean}㎡" if clean else ""

def calculate_ltv(total_value, deduction, principal_sum, maintain_maxamt_sum, ltv, is_senior=True):
    if is_senior:
        limit = int(total_value * (ltv / 100) - deduction)
        available = int(limit - principal_sum)
    else:
        limit = int(total_value * (ltv / 100) - maintain_maxamt_sum - deduction)
        available = int(limit - principal_sum)
    limit = (limit // 10) * 10
    available = (available // 10) * 10
    return limit, available


# ------------------------------
# 🔹 세션 초기화
# ------------------------------

for key in ["extracted_address", "extracted_area", "raw_price", "extracted_floor"]:
    if key not in st.session_state:
        st.session_state[key] = ""

# co_owners는 업로드되기 전이거나 불러오기도 아닌 경우만 빈 리스트로 초기화
if "co_owners" not in st.session_state and "uploaded_pdf_path" not in st.session_state and "load_customer_select" not in st.session_state:
    st.session_state["co_owners"] = []

if uploaded_file:
    # 1. PDF 텍스트 추출 및 메타정보 세션 저장
    text, external_links, address, area, floor, co_owners = process_pdf(uploaded_file)
    st.session_state["extracted_address"] = address
    st.session_state["extracted_area"] = area
    st.session_state["extracted_floor"] = floor
    st.session_state["co_owners"] = co_owners
    st.success(f"📍 PDF에서 주소 추출: {address}")

    # 2. 임시 PDF 파일 저장 (한번만)
    if "uploaded_pdf_path" not in st.session_state:
        uploaded_file.seek(0)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            st.session_state["uploaded_pdf_path"] = tmp_file.name

    pdf_path = st.session_state["uploaded_pdf_path"]
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()  # ✅ 꼭 닫아주세요!


    # 3. 페이지 인덱스 세션 초기화
    if "page_index" not in st.session_state:
        st.session_state.page_index = 0
    page_index = st.session_state.page_index


    # 4. 미리보기 이미지 렌더링
    # 좌측 페이지
    img1 = pdf_to_image(pdf_path, page_index)
    # 우측 페이지 (있을 경우)
    img2 = pdf_to_image(pdf_path, page_index + 1) if page_index + 1 < total_pages else None

    cols = st.columns(2)
    with cols[0]:
        if img1: st.image(img1, caption=f"{page_index + 1} 페이지")
    with cols[1]:
        if img2: st.image(img2, caption=f"{page_index + 2} 페이지")

    # 5. 이전/다음 버튼
    col_prev, _, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("⬅️ 이전 페이지") and page_index >= 2:
            st.session_state.page_index -= 2
    with col_next:
        if st.button("➡️ 다음 페이지") and page_index + 2 < total_pages:
            st.session_state.page_index += 2

    # 56. 외부 링크 경고
    if external_links:
        st.warning("📎 PDF 내부에 외부 링크가 포함되어 있습니다:")
        for uri in external_links:
            st.code(uri)

# ------------------------------
# 🔹 고객 선택 + 불러오기 + 삭제 UI
# ------------------------------

from history_manager import (
    get_customer_options,
    load_customer_input,
    delete_customer_from_notion,
    fetch_all_notion_customers
)

# Notion 데이터 최초 1회 로드
if "notion_customers" not in st.session_state:
    fetch_all_notion_customers()

# UI 구성
col1, col2 = st.columns([2, 1])

with col1:
    customer_list = get_customer_options()
    selected_customer = st.selectbox("고객 선택 (불러오기 또는 삭제)", [""] + customer_list, key="load_customer_select")

    if selected_customer:
        load_customer_input(selected_customer)

        # 🔒 안전한 세션 키 초기화
        for key in ["extracted_address", "extracted_area", "raw_price", "co_owners", "extracted_floor"]:
            if key not in st.session_state:
                st.session_state[key] = "" if key != "co_owners" else []

        st.success(f"✅ '{selected_customer}'님의 데이터가 불러와졌습니다.")

with col2:
    if selected_customer and st.button("🗑️ 선택한 고객 삭제하기"):
        delete_customer_from_notion(selected_customer)
        st.rerun()  # ✅ 삭제 후 전체 앱 새로고침

# ------------------------------
# 🔹 기본 정보 입력
# ------------------------------

st.markdown("📄 기본 정보 입력")

info_col1, info_col2 = st.columns(2)

with info_col1:
    address_input = st.text_input("주소", st.session_state["extracted_address"], key="address_input")

with info_col2:
    co_owners_raw = st.session_state.get("co_owners", [])
    if isinstance(co_owners_raw, str):
        try:
            temp = ast.literal_eval(co_owners_raw)
            co_owners = [tuple(s.split(",")) for s in temp if isinstance(s, str) and "," in s]
        except Exception:
            co_owners = []
    else:
        co_owners = [tuple(s.split(",")) for s in co_owners_raw if isinstance(s, str) and "," in s]

    default_name_text = f"{co_owners[0][0]}  {co_owners[0][1]}" if co_owners else ""

    if "customer_name" not in st.session_state:
        st.session_state["customer_name"] = default_name_text

    customer_name = st.text_input("고객명", placeholder=default_name_text, key="customer_name")

col1, col2 = st.columns(2)
with col1:
    region = st.selectbox("방공제 지역 선택", [""] + list(region_map.keys()))
    default_d = region_map.get(region, 0)

with col2:
    manual_d = st.text_input("방공제 금액 (만)", f"{default_d:,}")

col3, col4 = st.columns(2)

with col3:
    if "raw_price_input" not in st.session_state:
        # 불러온 값이 있으면 그것으로 초기화, 없으면 빈 문자열
        st.session_state["raw_price_input"] = st.session_state.get("raw_price_input_default", "")

    st.text_input("KB 시세 (만원)", key="raw_price_input", on_change=format_kb_price)

    
with col4:
    area_input = st.text_input("전용면적 (㎡)", value=st.session_state.get("extracted_area", ""), key="area_input")

# 🔒 deduction 계산
deduction = default_d
try:
    cleaned = re.sub(r"[^\d]", "", manual_d)
    if cleaned:
        deduction = int(cleaned)
except Exception as e:
    st.warning(f"방공제 금액 오류: 기본값({default_d})이 사용됩니다.")

# ------------------------------
# 🔹 층수 판단
# ------------------------------
floor_match = re.findall(r"제(\d+)층", address_input)
floor_num = int(floor_match[-1]) if floor_match else None
if floor_num is not None:
    if floor_num <= 2:
        st.markdown('<span style="color:red; font-weight:bold; font-size:18px">📉 하안가</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="color:#007BFF; font-weight:bold; font-size:18px">📈 일반가</span>', unsafe_allow_html=True)

# ------------------------------
# 🔹 시세 버튼 및 PDF 처리
# ------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("KB 시세 조회"):
        st.components.v1.html("<script>window.open('https://kbland.kr/map','_blank')</script>", height=0)

with col2:
    if st.button("하우스머치 시세조회"):
        st.components.v1.html("<script>window.open('https://www.howsmuch.com','_blank')</script>", height=0)

with col3:
    if "uploaded_pdf_path" in st.session_state:
        with open(st.session_state["uploaded_pdf_path"], "rb") as f:
            st.download_button(
                label="🌐 브라우저 새 탭에서 PDF 열기",
                data=f,
                file_name="uploaded.pdf",
                mime="application/pdf"
            )
    else:
        st.info("📄 먼저 PDF 파일을 업로드해 주세요.")

# ------------------------------
# 🔹 LTV 입력
# ------------------------------
st.markdown("---")
st.subheader("📌 LTV 비율 입력")

ltv_col1, ltv_col2 = st.columns(2)

with ltv_col1:
    raw_ltv1 = st.text_input("LTV 비율 ① (%)", "80")

with ltv_col2:
    raw_ltv2 = st.text_input("LTV 비율 ② (%)", "")

# 선택값 정리
ltv_selected = []
for val in [raw_ltv1, raw_ltv2]:
    try:
        v = int(val)
        if 1 <= v <= 100:
            ltv_selected.append(v)
    except:
        continue
ltv_selected = list(dict.fromkeys(ltv_selected))  # 중복 제거

# ------------------------------
# 🔹 대출 항목 입력
# ------------------------------

rows = st.number_input("대출 항목", min_value=0, max_value=10, value=3)
items = []

def format_with_comma(key):
    raw = st.session_state.get(key, "")
    clean = re.sub(r"[^\d]", "", raw)
    if clean.isdigit():
        st.session_state[key] = "{:,}".format(int(clean))
    else:
        st.session_state[key] = ""

for i in range(rows):
    cols = st.columns(5)

    lender = cols[0].text_input("설정자", key=f"lender_{i}")

    maxamt_key = f"maxamt_{i}"
    ratio_key = f"ratio_{i}"
    principal_key = f"principal_{i}"
    manual_flag_key = f"manual_{principal_key}"

    # 채권최고액 & 비율 입력
    max_amt = cols[1].text_input("채권최고액 (만)", key=maxamt_key, on_change=format_with_comma, args=(maxamt_key,))
    ratio = cols[2].text_input("설정비율 (%)", value="120", key=ratio_key)

    # 계산
    try:
        max_amt_val = int(re.sub(r"[^\d]", "", st.session_state.get(maxamt_key, "0")))
        ratio_val = int(re.sub(r"[^\d]", "", st.session_state.get(ratio_key, "120")))
        auto_calc = max_amt_val * 100 // ratio_val
    except:
        auto_calc = 0

    # 자동계산 상태 유지
    if manual_flag_key not in st.session_state:
        st.session_state[manual_flag_key] = False

    # 입력 변동 → 자동계산 되도록 재설정
    # 원금 필드가 수기입력 상태가 아니면 계산값으로 덮어쓰기
    if not st.session_state[manual_flag_key]:
        st.session_state[principal_key] = f"{auto_calc:,}"

    # 원금 필드 입력 시 → 수기입력으로 전환 + 포맷
    def on_manual_input(principal_key=principal_key, manual_flag_key=manual_flag_key):
        st.session_state[manual_flag_key] = True
        format_with_comma(principal_key)

    # 원금 입력 필드
    cols[3].text_input(
        "원금",
        key=principal_key,
        value=st.session_state.get(principal_key, ""),
        on_change=on_manual_input,
    )

    # 진행 구분
    status = cols[4].selectbox("진행구분", ["유지", "대환", "선말소"], key=f"status_{i}")

    items.append({
        "설정자": lender,
        "채권최고액": st.session_state.get(maxamt_key, ""),
        "설정비율": ratio,
        "원금": st.session_state.get(principal_key, ""),
        "진행구분": status
    })


# ------------------------------
# 🔹 LTV 계산부
# ------------------------------
raw_price_input = st.session_state.get("raw_price_input", "")
total_value = parse_korean_number(raw_price_input)

# ✅ 항상 초기화: 이후 오류 방지
limit_senior_dict = {}
limit_sub_dict = {}
valid_items = []

# ✅ 항상 초기화 (rows == 0 에도 필요)
sum_dh = 0
sum_sm = 0
sum_maintain = 0
sum_sub_principal = 0

if int(rows) == 0:
    st.markdown("### 📌 대출 항목이 없으므로 선순위 최대 LTV만 계산합니다")
    for ltv in ltv_selected:
        limit = int(total_value * (ltv / 100) - deduction)
        limit = (limit // 10) * 10
        limit_senior_dict[ltv] = (limit, limit)
else:
    # 진행구분별 합계 계산
    sum_dh = sum(
        int(re.sub(r"[^\d]", "", item.get("원금", "0")) or 0)
        for item in items if item.get("진행구분") == "대환"
    )
    sum_sm = sum(
        int(re.sub(r"[^\d]", "", item.get("원금", "0")) or 0)
        for item in items if item.get("진행구분") == "선말소"
    )
    sum_maintain = sum(
        int(re.sub(r"[^\d]", "", item.get("채권최고액", "0")) or 0)
        for item in items if item.get("진행구분") == "유지"
    )
    sum_sub_principal = sum(
        int(re.sub(r"[^\d]", "", item.get("원금", "0")) or 0)
        for item in items if item.get("진행구분") not in ["유지"]
    )

    # 유효 항목만 필터링
    valid_items = [item for item in items if any([
        item.get("설정자", "").strip(),
        re.sub(r"[^\d]", "", item.get("채권최고액", "") or "0") != "0",
        re.sub(r"[^\d]", "", item.get("원금", "") or "0") != "0"
    ])]


    # ✅ LTV 계산 함수
    def calculate_ltv(total_value, deduction, principal_sum, maintain_maxamt_sum, ltv, is_senior=True):
        if is_senior:
            limit = int(total_value * (ltv / 100) - deduction)
            available = int(limit - principal_sum)
        else:
            limit = int(total_value * (ltv / 100) - maintain_maxamt_sum - deduction)
            available = int(limit - principal_sum)
        limit = (limit // 10) * 10
        available = (available // 10) * 10
        return limit, available

    for ltv in ltv_selected:
        if sum_maintain > 0:
            limit_sub_dict[ltv] = calculate_ltv(total_value, deduction, sum_sub_principal, sum_maintain, ltv, is_senior=False)
        else:
            limit_senior_dict[ltv] = calculate_ltv(total_value, deduction, sum_dh + sum_sm, 0, ltv, is_senior=True)


# ------------------------------
# 🔹 결과 출력
# ------------------------------

text_to_copy = f"고객명 : {customer_name}\n주소 : {address_input}\n"
type_of_price = "하안가" if floor_num and floor_num <= 2 else "일반가"

# 시세 정리
clean_price = parse_korean_number(raw_price_input)
formatted_price = "{:,}".format(clean_price) if clean_price else raw_price_input
text_to_copy += f"{type_of_price} | KB시세: {formatted_price} | 전용면적 : {area_input} | 방공제 금액 : {deduction:,}만\n"

if valid_items:
    text_to_copy += "\n대출 항목\n"
    for item in valid_items:
        raw_max = re.sub(r"[^\d]", "", item.get("채권최고액", "0"))
        max_amt = int(raw_max) if raw_max else 0

        raw_principal = re.sub(r"[^\d]", "", item.get("원금", "0"))
        principal_amt = int(raw_principal) if raw_principal else 0

        text_to_copy += f"{item.get('설정자', '')} | 채권최고액: {max_amt:,} | 비율: {item.get('설정비율', '0')}% | 원금: {principal_amt:,} | {item.get('진행구분', '')}\n"


for ltv in ltv_selected:
    if ltv in limit_senior_dict:
        limit, avail = limit_senior_dict[ltv]
        text_to_copy += f"\n선순위 LTV {ltv}% {limit:,} 가용 {avail:,}"
    if ltv in limit_sub_dict:
        limit, avail = limit_sub_dict[ltv]
        text_to_copy += f"\n후순위 LTV {ltv}% {limit:,} 가용 {avail:,}"


text_to_copy += "\n진행구분별 원금 합계\n"
if sum_dh > 0:
    text_to_copy += f"대환: {sum_dh:,}만\n"
if sum_sm > 0:
    text_to_copy += f"선말소: {sum_sm:,}만\n"

# ✅ 결과내용 자동 생성 시 세션에 저장
st.session_state["text_to_copy"] = text_to_copy

# ✅ 출력은 세션 값만 보여줌 (value 제거)
st.text_area("결과 내용", height=320, key="text_to_copy")


# ------------------------------
# 🔹 수수료 계산부
# ------------------------------

import re

def format_with_commas(value):
    try:
        return f"{int(value):,}"
    except:
        return "0"

def parse_comma_number(text):
    try:
        return int(re.sub(r"[^\d]", "", text))
    except:
        return 0

col1, col2, col3, col4 = st.columns(4)

with col1:
    consult_input = st.text_input("컨설팅 금액 (만원)", "", key="consult_amt")
    consult_amount = parse_comma_number(consult_input)

with col2:
    consult_rate = st.number_input("컨설팅 수수료율 (%)", min_value=0.0, value=1.5, step=0.1, format="%.1f")

with col3:
    bridge_input = st.text_input("브릿지 금액 (만원)", "", key="bridge_amt")
    bridge_amount = parse_comma_number(bridge_input)

with col4:
    bridge_rate = st.number_input("브릿지 수수료율 (%)", min_value=0.0, value=0.7, step=0.1, format="%.1f")

# 수수료 계산
consult_fee = int(consult_amount * consult_rate / 100)
bridge_fee = int(bridge_amount * bridge_rate / 100)
total_fee = consult_fee + bridge_fee


# 출력
st.markdown(f"""
#### 수수료 합계: **{total_fee:,}만원**
- 컨설팅 수수료: {consult_fee:,}만원
- 브릿지 수수료: {bridge_fee:,}만원
""")

st.markdown("---")
st.markdown("### 💾 수동 저장")


# ------------------------------
# 🔹 수동 저장 버튼
# ------------------------------

if st.button("📌 이 입력 내용 저장하기", key="manual_save_button"):
    from history_manager import save_user_input
    save_user_input()
