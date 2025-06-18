import os
import re
import tempfile
import fitz
import streamlit as st
from datetime import datetime
from history_manager import (
    get_customer_options,
    load_customer_input,
    delete_customer_from_notion,
    fetch_all_notion_customers,
    create_new_customer,
    update_existing_customer,
)
from ltv_map import region_map

# ─────────────────────────────
# 🏠 페이지 설정 (가장 먼저 실행)
# ─────────────────────────────
st.set_page_config(
    page_title="LTV 계산기",
    page_icon="📊",
    layout="wide",
)

# ------------------------------
# 🔹 함수 정의
# ------------------------------
def process_pdf(uploaded_file):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    text = ""
    for page in doc: text += page.get_text("text")
    doc.close()
    return text

# ------------------------------
# 유틸 함수
# ------------------------------

def parse_comma_number(text):
    try:
        return int(re.sub(r"[^\d]", "", str(text)))
    except:
        return 0

# ✅ 콤마 + 만단위 절삭 함수 (100단위 절삭)

def format_with_comma(key):
    raw = st.session_state.get(key, "")
    clean = re.sub(r"[^\d]", "", str(raw))
    if clean.isdigit():
        val = int(clean)
        truncated = (val // 100) * 100
        st.session_state[key] = f"{truncated:,}"
    else:
        st.session_state[key] = ""

def format_kb_price():
    raw = st.session_state.get("raw_price_input", "")
    clean = parse_korean_number(raw)
    formatted = "{:,}".format(clean) if clean else ""
    st.session_state["raw_price"] = formatted
    st.session_state["raw_price_input"] = formatted  # ← 필드 표시값도 같이 갱신

def format_area():
    raw = st.session_state.get("area_input", "")
    clean = re.sub(r"[^\d.]", "", raw)
    st.session_state["extracted_area"] = f"{clean}㎡" if clean else ""
    
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

def parse_korean_number(text: str) -> int:
    txt = str(text).replace(",", "").strip()
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

# ─────────────────────────────
# 🔹 세션 초기화
# ─────────────────────────────

if "num_loan_items" not in st.session_state:
    st.session_state.num_loan_items = 1

for key in ["extracted_address", "extracted_area", "raw_price", "extracted_floor"]:
    if key not in st.session_state: st.session_state[key] = ""
if "co_owners" not in st.session_state: st.session_state["co_owners"] = []

# ─────────────────────────────
# 📎 PDF 업로드 및 처리
# ─────────────────────────────

# 🔹 파일 업로더
uploaded_file = st.file_uploader("📎 PDF 파일 업로드", type="pdf", key="pdf_uploader")

if uploaded_file:
    # PDF 처리 및 정보 추출 (기존 로직 유지)
    if "uploaded_pdf_path" not in st.session_state or st.session_state.get('uploaded_file_name') != uploaded_file.name:
        text, external_links, address, area, floor, co_owners = process_pdf(uploaded_file)
        st.session_state["extracted_address"] = address
        st.session_state["address_input"] = address
        st.session_state["extracted_area"] = area
        st.session_state["extracted_floor"] = floor
        st.session_state["co_owners"] = co_owners
        st.success(f"📍 PDF에서 주소 추출: {address}")

        if co_owners:
            st.session_state["customer_name"] = f"{co_owners[0][0]} {co_owners[0][1]}"

        uploaded_file.seek(0)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            st.session_state["uploaded_pdf_path"] = tmp_file.name
        
        st.session_state['uploaded_file_name'] = uploaded_file.name
        st.session_state.page_index = 0

    pdf_path = st.session_state["uploaded_pdf_path"]
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    if "page_index" not in st.session_state:
        st.session_state.page_index = 0
    page_index = st.session_state.page_index

    img1 = pdf_to_image(pdf_path, page_index)
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

    if 'external_links' in locals() and external_links:
        st.warning("📎 PDF 내부에 외부 링크가 포함되어 있습니다:")
        for uri in external_links:
            st.code(uri)


# ─────────────────────────────
# 🗂️ 고객 이력 관리 (최종 버전)
# ─────────────────────────────

if "notion_customers" not in st.session_state:
    fetch_all_notion_customers()

# 1. 고객을 선택하는 드롭다운 메뉴
selected_customer = st.selectbox(
    "고객 선택", [""] + get_customer_options(), key="load_customer_select", label_visibility="collapsed"
)
cols = st.columns(3)
with cols[0]:
    # 2. 고객이 선택되었을 때만 "불러오기" 버튼이 보임
    if selected_customer:
        if st.button("🔄 불러오기", use_container_width=True):
            load_customer_input(selected_customer) # 3. 버튼 클릭 시 데이터 로딩 함수 호출
            st.rerun()
# ... (삭제, 초기화 버튼)

with cols[1]:
    if selected_customer:
        if st.button("🗑️ 삭제", type="secondary", use_container_width=True):
            delete_customer_from_notion(selected_customer)
            st.rerun()
with cols[2]:
    st.button("✨ 전체 초기화", on_click=reset_app_state, use_container_width=True)

# ─────────────────────────────
# 📄 기본 정보 입력 (수정된 버전)
# ─────────────────────────────

st.subheader("기본 정보 입력")

col1, col2 = st.columns(2)
with col1:
    st.text_input("주소", key="address_input")
with col2:
    st.text_input("고객명 및 생년월일", key="customer_name")

col1, col2 = st.columns(2)
with col1:
    # 1. 사용자가 드롭다운에서 지역을 선택하면 페이지가 새로고침됩니다.
    region = st.selectbox("방공제 지역", [""] + list(region_map.keys()), key="region")
    
with col2:
    # 2. 선택된 지역에 맞는 금액을 찾습니다.
    default_d = region_map.get(region, 0)

    # 3. [핵심 수정] 현재 선택된 지역이 '이전 지역'과 다를 경우에만
    #    방공제 금액을 새로운 기본값으로 덮어씁니다.

    if st.session_state.get("current_region") != region:
        st.session_state.manual_d = f"{default_d:,}"
        st.session_state.current_region = region # '이전 지역'을 현재 지역으로 업데이트

    # 4. 방공제 금액 입력칸을 그립니다. 값은 위 로직에 의해 결정됩니다.
    st.text_input("방공제 금액 (만)", key="manual_d", on_change=format_with_comma, args=("manual_d",))

col3, col4 = st.columns(2)
with col3:
    st.text_input("KB 시세 (만원)", key="raw_price_input", on_change=format_kb_price)
with col4:
    st.text_input("전용면적 (㎡)", value=st.session_state.get("extracted_area", ""), key="area_input")

# 이 아래의 코드는 기존과 동일하게 유지합니다.

try:
    cleaned = re.sub(r"[^\d]", "", str(st.session_state.get("manual_d", "")))
    deduction = int(cleaned) if cleaned else default_d
except:
    deduction = default_d

address_input = st.session_state.get("address_input", "")
floor_match = re.findall(r"제(\d+)층", address_input)
floor_num = int(floor_match[-1]) if floor_match else None
if floor_num is not None:
    if floor_num <= 2:
        st.markdown('<span style="color:red; font-weight:bold; font-size:18px">📉 하안가</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="color:#007BFF; font-weight:bold; font-size:18px">📈 일반가</span>', unsafe_allow_html=True)

# ─────────────────────────────
# 시세/외부사이트 버튼
# ─────────────────────────────

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

# ─────────────────────────────
# 🔹 LTV 입력
# ─────────────────────────────

ltv_col1, ltv_col2 = st.columns(2)
with ltv_col1: st.text_input("LTV 비율 ① (%)", "80", key="ltv1")
with ltv_col2: st.text_input("LTV 비율 ② (%)", "", key="ltv2")

ltv_selected = [int(v) for key in ("ltv1", "ltv2") if (v := st.session_state.get(key, "")) and v.isdigit() and 1 <= int(v) <= 100]
ltv_selected = sorted(list(dict.fromkeys(ltv_selected)), reverse=True)
st.session_state["ltv_selected"] = ltv_selected

# ─────────────────────────────
# 대출 항목 입력 (최종 수정본)
# ─────────────────────────────
st.markdown("---")
st.subheader("대출 항목 입력")

def bidirectional_loan_calculator(maxamt_key, ratio_key, principal_key):
    """하나의 대출 항목에 대한 양방향 자동 계산을 수행하는 콜백 함수"""
    try:
        # 현재 세션 상태의 값들을 가져옴
        max_amt_str = st.session_state.get(maxamt_key, "")
        ratio_str = st.session_state.get(ratio_key, "")
        principal_str = st.session_state.get(principal_key, "")

        # 마지막으로 포커스가 있었던 위젯(방금 사용자가 수정한 위젯)을 확인
        last_active_widget = st.session_state.get("last_active_loan_widget")

        # 숫자 값으로 변환
        max_val = parse_comma_number(max_amt_str)
        rat_val = parse_comma_number(ratio_str)
        pri_val = parse_comma_number(principal_str)
        
        if rat_val > 0:
            # 사용자가 '채권최고액' 또는 '비율'을 수정했고, '원금'이 비어있거나 자동계산 대상일 때
            if last_active_widget in [maxamt_key, ratio_key]:
                calculated_pri = int(max_val * 100 / rat_val)
                st.session_state[principal_key] = f"{calculated_pri:,}"
            # 사용자가 '원금'을 수정했을 때
            elif last_active_widget == principal_key:
                calculated_max = int(pri_val * rat_val / 100)
                st.session_state[maxamt_key] = f"{calculated_max:,}"

    except (ValueError, ZeroDivisionError):
        pass

def set_active_widget(key):
    """어떤 위젯이 마지막으로 활성화되었는지 기록하는 헬퍼 함수"""
    st.session_state["last_active_loan_widget"] = key


st.number_input(
    "대출 항목 개수",
    min_value=1,
    key="num_loan_items"
)

items = []
for i in range(st.session_state.get("num_loan_items", 1)):
    lender_key, maxamt_key, ratio_key, principal_key, status_key = f"lender_{i}", f"maxamt_{i}", f"ratio_{i}", f"principal_{i}", f"status_{i}"

    # --- [최종 수정] 엑셀처럼 작동하는 양방향 계산 로직 ---

    # 1. '직전 실행' 때의 값을 불러옵니다.
    prev_max_val = st.session_state.get(f"prev_max_{i}", 0)
    prev_pri_val = st.session_state.get(f"prev_pri_{i}", 0)
    prev_rat_val = st.session_state.get(f"prev_rat_{i}", 0)

    # 2. 현재 입력된 값을 숫자로 변환합니다.
    max_val = parse_comma_number(st.session_state.get(maxamt_key, ""))
    pri_val = parse_comma_number(st.session_state.get(principal_key, ""))
    rat_val = parse_comma_number(st.session_state.get(ratio_key, ""))

    # 3. 계산 로직 실행: 마지막으로 수정한 값을 기준으로 다른 값을 계산합니다.
    try:
        # 규칙 1: 원금이 수정되었다면 (최우선), 채권최고액을 재계산
        if pri_val != prev_pri_val:
            if rat_val > 0:
                new_max = f"{int(pri_val * rat_val / 100):,}"
                st.session_state[maxamt_key] = new_max
        # 규칙 2: 원금은 그대로인데, 채권최고액이나 비율이 수정되었다면, 원금을 재계산
        elif max_val != prev_max_val or rat_val != prev_rat_val:
            if max_val > 0 and rat_val > 0:
                new_pri = f"{int(max_val * 100 / rat_val):,}"
                st.session_state[principal_key] = new_pri
    except (ValueError, ZeroDivisionError):
        pass

    # 4. 위젯을 그립니다.
    cols = st.columns(5)
    with cols[0]:
        st.text_input(f"설정자 {i+1}", key=lender_key, label_visibility="collapsed", placeholder=f"{i+1}. 설정자")
    with cols[1]:
        st.text_input(f"채권최고액 {i+1}", key=maxamt_key, on_change=format_with_comma, args=(maxamt_key,), label_visibility="collapsed", placeholder="채권최고액 (만)")
    with cols[2]:
        st.text_input(f"설정비율 {i+1}", key=ratio_key, label_visibility="collapsed", placeholder="설정비율 (%)")
    with cols[3]:
        st.text_input(f"원금 {i+1}", key=principal_key, on_change=format_with_comma, args=(principal_key,), label_visibility="collapsed", placeholder="원금 (만)")
    with cols[4]:
        st.selectbox(f"진행구분 {i+1}", ["유지", "대환", "선말소"], key=status_key, index=0, label_visibility="collapsed")

    # 5. 다음 실행을 위해 현재 값을 '직전 값'으로 저장합니다.
    st.session_state[f"prev_max_{i}"] = parse_comma_number(st.session_state.get(maxamt_key))
    st.session_state[f"prev_pri_{i}"] = parse_comma_number(st.session_state.get(principal_key))
    st.session_state[f"prev_rat_{i}"] = parse_comma_number(st.session_state.get(ratio_key))
    
    items.append({
        "설정자": st.session_state.get(lender_key, ""),
        "채권최고액": st.session_state.get(maxamt_key, ""),
        "설정비율": st.session_state.get(ratio_key, ""),
        "원금": st.session_state.get(principal_key, ""),
        "진행구분": st.session_state.get(status_key, "유지")
    })

# ─────────────────────────────
# [요청 3] 수수료 계산부 위치 이동
# ─────────────────────────────

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.text_input("컨설팅 금액 (만원)", key="consult_amt", on_change=format_with_comma, args=("consult_amt",))
    consult_amount = parse_comma_number(st.session_state.get("consult_amt", "0"))
with col2:
    consult_rate = st.number_input("컨설팅 수수료율 (%)", min_value=0.0, value=1.5, step=0.1, format="%.1f", key="consult_rate")
with col3:
    st.text_input("브릿지 금액 (만원)", key="bridge_amt", on_change=format_with_comma, args=("bridge_amt",))
    bridge_amount = parse_comma_number(st.session_state.get("bridge_amt", "0"))
with col4:
    bridge_rate = st.number_input("브릿지 수수료율 (%)", min_value=0.0, value=0.7, step=0.1, format="%.1f", key="bridge_rate")

consult_fee = int(consult_amount * consult_rate / 100)
bridge_fee = int(bridge_amount * bridge_rate / 100)
total_fee = consult_fee + bridge_fee

# ─────────────────────────────
# 📋 LTV 계산/결과 메모 생성/출력 (기존 복잡한 로직 유지)
# ─────────────────────────────
st.subheader("📋 결과 내용")

rows = st.session_state.get("num_loan_items", 0)
try:
    rows = int(rows)
except:
    rows = 0

raw_price_input = st.session_state.get("raw_price_input", "")
total_value = parse_korean_number(raw_price_input)
limit_senior_dict, limit_sub_dict, valid_items = {}, {}, []
sum_dh = sum_sm = sum_maintain = sum_sub_principal = 0

if rows == 0:
    for ltv in ltv_selected:
        limit = int(total_value * (ltv / 100) - deduction)
        limit = (limit // 10) * 10
        limit_senior_dict[ltv] = (limit, limit)
else:
    sum_dh = sum(
        int(re.sub(r"[^\d]", "", str(item.get("원금", "0"))) or 0)
        for item in items if item.get("진행구분") == "대환"
    )
    sum_sm = sum(
        int(re.sub(r"[^\d]", "", str(item.get("원금", "0"))) or 0)
        for item in items if item.get("진행구분") == "선말소"
    )
    sum_maintain = sum(
        int(re.sub(r"[^\d]", "", str(item.get("채권최고액", "0"))) or 0)
        for item in items if item.get("진행구분") == "유지"
    )
    sum_sub_principal = sum(
        int(re.sub(r"[^\d]", "", str(item.get("원금", "0"))) or 0)
        for item in items if item.get("진행구분") not in ["유지"]
    )
    valid_items = [item for item in items if any([
        item.get("설정자", "").strip(),
        re.sub(r"[^\d]", "", str(item.get("채권최고액", "") or "0")) != "0",
        re.sub(r"[^\d]", "", str(item.get("원금", "") or "0")) != "0"
    ])]

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

# --- [수정된 결과 메모 생성 코드] ---
# 결과 메모 자동생성
customer_name = st.session_state.get("customer_name", "")
address_input = st.session_state.get("address_input", "")
area_input = st.session_state.get("area_input", "")
type_of_price = "하안가" if floor_num and floor_num <= 2 else "일반가"
clean_price = parse_korean_number(raw_price_input)
formatted_price = "{:,}".format(clean_price) if clean_price else raw_price_input
text_to_copy = f"고객명 : {customer_name}\n주소 : {address_input}\n"
text_to_copy += f"{type_of_price} | KB시세: {formatted_price} | 전용면적 : {area_input} | 방공제 금액 : {deduction:,}만\n"
if valid_items:
    text_to_copy += "\n[대출 항목]\n"
    for item in valid_items:
        raw_max = re.sub(r"[^\d]", "", str(item.get("채권최고액", "0")))
        max_amt = int(raw_max) if raw_max else 0
        raw_principal = re.sub(r"[^\d]", "", str(item.get("원금", "0")))
        principal_amt = int(raw_principal) if raw_principal else 0
        text_to_copy += f"{item.get('설정자', '')} | 채권최고액: {max_amt:,} | 원금: {principal_amt:,} | {item.get('진행구분', '')}\n"

for ltv in ltv_selected:
    if ltv in limit_senior_dict:
        limit, avail = limit_senior_dict[ltv]
        text_to_copy += f"\n[선순위 LTV {ltv}%] 한도: {limit:,}만 | 가용: {avail:,}만"
    if ltv in limit_sub_dict:
        limit, avail = limit_sub_dict[ltv]
        text_to_copy += f"\n[후순위 LTV {ltv}%] 한도: {limit:,}만 | 가용: {avail:,}만"

text_to_copy += "\n[진행구분별 원금 합계]\n"
if sum_dh > 0: text_to_copy += f"대환: {sum_dh:,}만\n"
if sum_sm > 0: text_to_copy += f"선말소: {sum_sm:,}만\n"

# [수정] 수수료 정보를 결과 메모 하단에 상세하게 추가합니다.
text_to_copy += f"""
[수수료 정보]
컨설팅: {consult_amount:,}만 (수수료: {consult_fee:,}만)
브릿지: {bridge_amount:,}만 (수수료: {bridge_fee:,}만)
총 합계: {total_fee:,}만
"""

st.text_area("복사할 내용", text_to_copy, height=400, key="text_to_copy")

# ─────────────────────────────
# 💾 저장 / 수정 버튼
# ─────────────────────────────

st.subheader("💾 저장 / 수정")
col1, col2 = st.columns(2)
with col1:
    if st.button("💾 신규 고객으로 저장", use_container_width=True):
        create_new_customer()
with col2:
    if st.button("🔄 기존 고객 정보 수정", use_container_width=True, type="primary"):
        update_existing_customer()

