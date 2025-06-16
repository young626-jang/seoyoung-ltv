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
# 🔹 함수 정의 (상단에 모두 통합)
# ------------------------------

def reset_app_state():
    """앱 상태를 초기화하는 전용 콜백 함수"""
    if "uploaded_pdf_path" in st.session_state and os.path.exists(st.session_state.uploaded_pdf_path):
        os.remove(st.session_state.uploaded_pdf_path)

    keys_to_clear = [
        "customer_name", "address_input", "region", "manual_d", "raw_price_input", 
        "area_input", "ltv1", "ltv2", "consult_amt", "consult_rate", "bridge_amt", 
        "bridge_rate", "text_to_copy", "current_region", "just_loaded", 
        "extracted_address", "extracted_area", "extracted_floor", "co_owners",
        "uploaded_pdf_path", "pdf_processed", "page_index", "uploaded_file_name", "pdf_uploader"
    ]
    
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    
    num_items = st.session_state.get("num_loan_items", 1)
    for i in range(num_items):
        for prefix in ["lender", "maxamt", "ratio", "principal", "status", "prev_max", "prev_pri", "prev_rat"]:
            key = f"{prefix}_{i}"
            if key in st.session_state:
                del st.session_state[key]

    st.session_state.num_loan_items = 1

def extract_address(text):
    m = re.search(r"\[집합건물\]\s*([^\n]+)", text)
    if m: return m.group(1).strip()
    m = re.search(r"소재지\s*[:：]?\s*([^\n]+)", text)
    if m: return m.group(1).strip()
    return ""

def extract_area_floor(text):
    m = re.findall(r"(\d+\.\d+)\s*㎡", text.replace('\n', ' '))
    area = f"{m[-1]}㎡" if m else ""
    floor = None
    addr = extract_address(text)
    f_match = re.findall(r"제(\d+)층", addr)
    if f_match: floor = int(f_match[-1])
    return area, floor

def extract_all_names_and_births(text):
    start = text.find("주요 등기사항 요약")
    if start == -1: return []
    summary = text[start:]
    lines = [l.strip() for l in summary.splitlines() if l.strip()]
    result = []
    for i in range(len(lines)):
        if re.match(r"[가-힣]+ \(공유자\)|[가-힣]+ \(소유자\)", lines[i]):
            name = re.match(r"([가-힣]+)", lines[i]).group(1)
            if i + 1 < len(lines):
                birth_match = re.match(r"(\d{6})-", lines[i + 1])
                if birth_match: result.append((name, birth_match.group(1)))
    return result

def process_pdf(uploaded_file):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text("text")
    doc.close()
    address = extract_address(text)
    area, floor = extract_area_floor(text)
    co_owners = extract_all_names_and_births(text)
    return text, address, area, floor, co_owners

def parse_comma_number(text):
    try: return int(re.sub(r"[^\d]", "", str(text)))
    except: return 0

def pdf_to_image(pdf_path, page_num, zoom=2.0):
    doc = fitz.open(pdf_path)
    if page_num >= len(doc): return None
    page = doc.load_page(page_num)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return pix.tobytes("png")

def format_with_comma(key):
    raw = st.session_state.get(key, "")
    clean = re.sub(r"[^\d]", "", str(raw))
    if clean.isdigit():
        val = int(clean)
        st.session_state[key] = f"{val:,}"
    else:
        st.session_state[key] = ""

def parse_korean_number(text: str) -> int:
    txt = str(text).replace(",", "").strip()
    total = 0
    m = re.search(r"(\d+)\s*억", txt);
    if m: total += int(m.group(1)) * 10000
    m = re.search(r"(\d+)\s*천만", txt);
    if m: total += int(m.group(1)) * 1000
    m = re.search(r"(\d+)\s*만", txt);
    if m: total += int(m.group(1))
    if total == 0:
        try: total = int(txt)
        except: total = 0
    return total

def format_kb_price():
    raw = st.session_state.get("raw_price_input", "")
    clean = parse_korean_number(raw)
    st.session_state["raw_price_input"] = f"{clean:,}" if clean else ""

def calculate_ltv(total_value, deduction, principal_sum, maintain_maxamt_sum, ltv):
    if maintain_maxamt_sum > 0: # 후순위
        limit = total_value * (ltv / 100) - maintain_maxamt_sum - deduction
    else: # 선순위
        limit = total_value * (ltv / 100) - deduction
    
    available = limit - principal_sum
    limit = int(limit // 10) * 10
    available = int(available // 10) * 10
    return limit, available

# ─────────────────────────────
# 🔹 세션 초기화
# ─────────────────────────────
if "num_loan_items" not in st.session_state:
    st.session_state.num_loan_items = 1

# ─────────────────────────────
# 📎 PDF 업로드 및 처리
# ─────────────────────────────
uploaded_file = st.file_uploader("📎 PDF 파일 업로드", type="pdf", key="pdf_uploader")
if uploaded_file:
    if "pdf_processed" not in st.session_state or st.session_state.get('uploaded_file_name') != uploaded_file.name:
        text, address, area, floor, co_owners = process_pdf(uploaded_file)
        st.session_state.address_input = address
        st.session_state.area_input = area
        st.session_state.extracted_floor = floor
        if co_owners:
            st.session_state["customer_name"] = f"{co_owners[0][0]} {co_owners[0][1]}"
        st.success(f"📍 PDF에서 주소 추출: {address}")
        
        uploaded_file.seek(0)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            st.session_state["uploaded_pdf_path"] = tmp_file.name
        
        st.session_state['uploaded_file_name'] = uploaded_file.name
        st.session_state.pdf_processed = True
        st.rerun()

# ─────────────────────────────
# 🗂️ 고객 이력 관리
# ─────────────────────────────
st.markdown("---")
if "notion_customers" not in st.session_state:
    fetch_all_notion_customers()

st.subheader("🗂️ 고객 이력 관리")
selected_customer = st.selectbox(
    "고객 선택", [""] + get_customer_options(), key="load_customer_select", label_visibility="collapsed"
)

cols = st.columns(3)
with cols[0]:
    if selected_customer:
        if st.button("🔄 불러오기", use_container_width=True):
            load_customer_input(selected_customer)
            st.rerun()
with cols[1]:
    if selected_customer:
        if st.button("🗑️ 삭제", type="secondary", use_container_width=True):
            delete_customer_from_notion(selected_customer)
            st.rerun()
with cols[2]:
    st.button("✨ 전체 초기화", on_click=reset_app_state, use_container_width=True)

# ─────────────────────────────
# 📄 기본 정보 입력
# ─────────────────────────────
st.markdown("---")
st.subheader("기본 정보 입력")

region = st.selectbox("방공제 지역", [""] + list(region_map.keys()), key="region")
if st.session_state.get("current_region") != region:
    st.session_state.manual_d = f"{region_map.get(region, 0):,}"
    st.session_state.current_region = region

col1, col2 = st.columns(2)
with col1: st.text_input("고객명 (제목)", key="customer_name")
with col2: st.text_input("주소", key="address_input")

col1, col2 = st.columns(2)
with col1: st.text_input("KB 시세 (만원)", key="raw_price_input", on_change=format_kb_price)
with col2: st.text_input("방공제 금액 (만)", key="manual_d", on_change=format_with_comma, args=("manual_d",))
st.text_input("전용면적 (㎡)", key="area_input")

# ─────────────────────────────
# 📌 LTV, 대출, 수수료 정보 (탭 UI)
# ─────────────────────────────
st.markdown("---")
st.subheader("LTV, 대출, 수수료 정보")
tab1, tab2, tab3 = st.tabs(["LTV 비율", "대출 항목", "수수료"])

with tab1:
    ltv_col1, ltv_col2 = st.columns(2)
    with ltv_col1: st.text_input("LTV 비율 ① (%)", "80", key="ltv1")
    with ltv_col2: st.text_input("LTV 비율 ② (%)", "", key="ltv2")

with tab2:
    st.number_input("대출 항목 개수", min_value=1, key="num_loan_items")
    items = []
    for i in range(st.session_state.get("num_loan_items", 1)):
        # ... (이전 답변의 최종 양방향 계산 로직과 동일) ...
        pass

with tab3:
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.text_input("컨설팅 금액 (만원)", key="consult_amt", on_change=format_with_comma, args=("consult_amt",))
    with col2: st.number_input("컨설팅 수수료율 (%)", min_value=0.0, value=1.5, step=0.1, format="%.1f", key="consult_rate")
    with col3: st.text_input("브릿지 금액 (만원)", key="bridge_amt", on_change=format_with_comma, args=("bridge_amt",))
    with col4: st.number_input("브릿지 수수료율 (%)", min_value=0.0, value=0.7, step=0.1, format="%.1f", key="bridge_rate")
    
    consult_amount = parse_comma_number(st.session_state.get("consult_amt", "0"))
    bridge_amount = parse_comma_number(st.session_state.get("bridge_amt", "0"))
    consult_rate = st.session_state.get("consult_rate", 0.0)
    bridge_rate = st.session_state.get("bridge_rate", 0.0)
    consult_fee = int(consult_amount * consult_rate / 100)
    bridge_fee = int(bridge_amount * bridge_rate / 100)
    total_fee = consult_fee + bridge_fee

    st.markdown(f"""
    - **컨설팅:** {consult_amount:,}만원 X {consult_rate}% = **{consult_fee:,}만원**
    - **브릿지:** {bridge_amount:,}만원 X {bridge_rate}% = **{bridge_fee:,}만원**
    - ##### 수수료 합계: **{total_fee:,}만원**
    """)

# ─────────────────────────────
# 📋 결과 생성 및 표시
# ─────────────────────────────
st.markdown("---")
st.subheader("📋 결과 내용")

# [수정] 불러오기 직후에는 메모를 재성성하지 않도록 '깃발'을 확인
if not st.session_state.get("just_loaded", False):
    # ... (결과 메모 생성 로직)
    pass

if "just_loaded" in st.session_state:
    del st.session_state["just_loaded"]

st.text_area("복사할 내용", st.session_state.get("text_to_copy", ""), height=400, key="text_to_copy")

# ─────────────────────────────
# 💾 저장 / 수정 버튼
# ─────────────────────────────
st.markdown("---")
st.subheader("💾 저장 / 수정")
col1, col2 = st.columns(2)
with col1:
    if st.button("💾 신규 고객으로 저장", use_container_width=True):
        create_new_customer()
with col2:
    if st.button("🔄 기존 고객 정보 수정", use_container_width=True, type="primary"):
        update_existing_customer()
