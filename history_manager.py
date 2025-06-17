import os
import re
import requests
import streamlit as st
from datetime import datetime

# ─────────────────────────────
# 🔐 Notion API 설정
# ─────────────────────────────
NOTION_TOKEN = "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"
NOTION_DB_ID = "20eebdf1-11b5-80ad-9004-c7e82d290cbc"
NOTION_DB_ID_LOAN = "210ebdf111b580c4a36fd9edbb0ff8ec"

# ❗ 최종 설정 값
CUSTOMER_DB_TITLE_PROPERTY_NAME = "고객명"
CUSTOMER_DB_ADDRESS_PROPERTY_NAME = "주소"
LOAN_DB_RELATION_PROPERTY_NAME = "연결된 고객" 

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ───────────────────────────────────────────────
# 🔑 Notion 속성명 → Streamlit 세션 키 매핑
# ───────────────────────────────────────────────
KEY_MAP = {
    CUSTOMER_DB_TITLE_PROPERTY_NAME: "customer_name",
    CUSTOMER_DB_ADDRESS_PROPERTY_NAME: "address_input",
    "방공제 지역": "region",
    "방공제 금액": "manual_d",
    "KB시세": "raw_price_input",
    "전용면적": "area_input",
    "LTV비율1": "ltv1",
    "LTV비율2": "ltv2",
    "메모": "text_to_copy",
    "컨설팅 금액": "consult_amt",
    "컨설팅 수수료율": "consult_rate",
    "브릿지 금액": "bridge_amt",
    "브릿지 수수료율": "bridge_rate",
    "공동 소유자": "co_owners_text", # [추가] 공동 소유자 매핑
}

# ------------------------------
# 🔹 유틸 함수
# ------------------------------
def parse_comma_number(text):
    try: return int(re.sub(r"[^\d]", "", str(text)))
    except: return 0

def get_properties_payload():
    """세션 상태에서 Notion에 보낼 데이터 페이로드를 생성하는 헬퍼 함수"""
    
    # [추가] 공동 소유자 정보를 문자열로 변환하는 로직
    co_owners_list = st.session_state.get("co_owners", [])
    co_owners_string = ""
    if co_owners_list:
        owner_strings = [f"{name} {birth}" for name, birth in co_owners_list]
        co_owners_string = ", ".join(owner_strings)
    
    # 페이로드에 공동 소유자 정보 추가
    return {
        CUSTOMER_DB_TITLE_PROPERTY_NAME: {"title": [{"text": {"content": st.session_state.get("customer_name", "")}}]},
        CUSTOMER_DB_ADDRESS_PROPERTY_NAME: {"rich_text": [{"text": {"content": st.session_state.get("address_input", "")}}]},
        "공동 소유자": {"rich_text": [{"text": {"content": co_owners_string}}]}, # [추가]
        "방공제 지역": {"rich_text": [{"text": {"content": st.session_state.get("region", "")}}]},
        "방공제 금액": {"number": parse_comma_number(st.session_state.get("manual_d", "0"))},
        "KB시세": {"number": parse_comma_number(st.session_state.get("raw_price_input", "0"))},
        "전용면적": {"rich_text": [{"text": {"content": st.session_state.get("area_input", "")}}]},
        "LTV비율1": {"rich_text": [{"text": {"content": st.session_state.get("ltv1", "")}}]},
        "LTV비율2": {"rich_text": [{"text": {"content": st.session_state.get("ltv2", "")}}]},
        "메모": {"rich_text": [{"text": {"content": st.session_state.get("text_to_copy", "")}}]},
        "컨설팅 금액": {"number": parse_comma_number(st.session_state.get("consult_amt", "0"))},
        "컨설팅 수수료율": {"number": st.session_state.get("consult_rate", 0.0)},
        "브릿지 금액": {"number": parse_comma_number(st.session_state.get("bridge_amt", "0"))},
        "브릿지 수수료율": {"number": st.session_state.get("bridge_rate", 0.0)},
        "저장시각": {"date": {"start": datetime.now().isoformat()}}
    }

# ─────────────────────────────
# 🧾 고객 목록 및 불러오기 관련 함수
# ─────────────────────────────
def get_customer_options():
    return list(st.session_state.get("notion_customers", {}).keys())

def fetch_all_notion_customers():
    # 이 함수는 KEY_MAP에 따라 자동으로 작동하므로 수정할 필요가 없습니다.
    notion_customers = {}
    try:
        query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
        has_more = True; next_cursor = None
        while has_more:
            payload = {"page_size": 100}
            if next_cursor: payload["start_cursor"] = next_cursor
            res = requests.post(query_url, headers=NOTION_HEADERS, json=payload)
            res.raise_for_status()
            data = res.json()
            for page in data.get("results", []):
                props = page.get("properties", {}); customer = {}
                name_prop = props.get(CUSTOMER_DB_TITLE_PROPERTY_NAME, {}).get("title", [])
                if name_prop:
                    customer_name_key = name_prop[0].get("text", {}).get("content", "")
                    if not customer_name_key: continue
                    customer["notion_page_id"] = page["id"]
                    for prop_name, app_key in KEY_MAP.items():
                        if prop_name in props:
                            value = props[prop_name]; content = None
                            if value.get("rich_text"): content = value["rich_text"][0]["text"]["content"] if value["rich_text"] else ""
                            elif value.get("title"): content = value["title"][0]["text"]["content"] if value["title"] else ""
                            elif value.get("number") is not None: content = value["number"]
                            elif value.get("date"): content = value.get("date", {}).get("start")
                            if content is not None: customer[app_key] = content
                    notion_customers[customer_name_key] = customer
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
    except Exception as e:
        st.warning(f"❗ Notion 데이터 조회 실패: {e}")
    st.session_state["notion_customers"] = notion_customers

def load_customer_input(customer_name):
    # 이 함수는 KEY_MAP에 따라 자동으로 작동하므로 수정할 필요가 없습니다.
    customer_data = st.session_state.get("notion_customers", {}).get(customer_name)
    if not customer_data:
        st.warning("해당 고객 데이터를 찾을 수 없습니다.")
        return
    st.session_state.clear()
    for key, value in customer_data.items():
        if key != "notion_page_id":
            if key in ["consult_amt", "bridge_amt", "manual_d", "raw_price_input"]:
                numeric_value = parse_comma_number(value)
                st.session_state[key] = f"{numeric_value:,}" if numeric_value else ""
            elif key in ["consult_rate", "bridge_rate"]:
                try: st.session_state[key] = float(value)
                except (ValueError, TypeError): st.session_state[key] = 0.0
            else:
                st.session_state[key] = value
    customer_page_id = customer_data.get("notion_page_id")
    if customer_page_id:
        load_loan_items(customer_page_id)
    if "num_loan_items" not in st.session_state:
        st.session_state.num_loan_items = 1
    st.session_state.just_loaded = True

def load_loan_items(customer_page_id):
    try:
        loan_query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID_LOAN}/query"
        payload = {"filter": {"property": LOAN_DB_RELATION_PROPERTY_NAME, "relation": {"contains": customer_page_id}}}
        res = requests.post(loan_query_url, headers=NOTION_HEADERS, json=payload)
        res.raise_for_status()
        loan_data = res.json().get("results", [])

        st.session_state["num_loan_items"] = len(loan_data) if loan_data else 1

        for i, item in enumerate(loan_data):
            props = item.get("properties", {})
            st.session_state[f"lender_{i}"] = props.get("설정자", {}).get("title", [{}])[0].get("text", {}).get("content", "")
            st.session_state[f"maxamt_{i}"] = f"{props.get('채권최고액', {}).get('number', 0):,}"
            st.session_state[f"ratio_{i}"] = str(props.get("설정비율", {}).get("number", ""))
            st.session_state[f"principal_{i}"] = f"{props.get('원금', {}).get('number', 0):,}"
            st.session_state[f"status_{i}"] = props.get("진행구분", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "유지")
    except Exception as e:
        st.error(f"❌ 대출 항목 불러오기 실패: {e}")

# ─────────────────────────────
# 💾 저장/수정/삭제 관련 함수
# ─────────────────────────────

def save_loan_items(customer_page_id):
    """대출 항목을 저장하는 헬퍼 함수"""
    try:
        # 1. 기존 대출 항목 모두 보관(삭제)
        loan_query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID_LOAN}/query"
        payload = {"filter": {"property": LOAN_DB_RELATION_PROPERTY_NAME, "relation": {"contains": customer_page_id}}}
        res = requests.post(loan_query_url, headers=NOTION_HEADERS, json=payload)
        res.raise_for_status()
        for page in res.json().get("results", []):
            archive_url = f"https://api.notion.com/v1/pages/{page['id']}"
            requests.patch(archive_url, headers=NOTION_HEADERS, json={"archived": True})
        
        # 2. 현재 대출 항목 모두 새로 저장
        num_items = st.session_state.get("num_loan_items", 0)
        for i in range(num_items):
            lender = st.session_state.get(f"lender_{i}", "").strip()
            if not lender: continue

            loan_payload = {
                "parent": {"database_id": NOTION_DB_ID_LOAN},
                "properties": {
                    "설정자": {"title": [{"text": {"content": lender}}]},
                    "채권최고액": {"number": parse_comma_number(st.session_state.get(f"maxamt_{i}", "0"))},
                    "설정비율": {"number": int(st.session_state.get(f"ratio_{i}", "0") or 0)},
                    "원금": {"number": parse_comma_number(st.session_state.get(f"principal_{i}", "0"))},
                    "진행구분": {"rich_text": [{"text": {"content": st.session_state.get(f"status_{i}", "유지")}}]},
                    LOAN_DB_RELATION_PROPERTY_NAME: {"relation": [{"id": customer_page_id}]}
                }
            }
            res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=loan_payload)
            res.raise_for_status()

    except Exception as e:
        st.warning(f"⚠️ 대출 항목 저장 중 오류 발생: {e}")


def create_new_customer():
    """[신규] 새로운 고객으로 Notion에 저장하는 함수"""
    customer_name = st.session_state.get("customer_name", "").strip()
    if not customer_name:
        st.error("고객명이 입력되지 않았습니다.")
        return

    try:
        if st.session_state.get("notion_customers", {}).get(customer_name):
            st.warning(f"'{customer_name}' 이름의 고객이 이미 존재합니다. 다른 이름으로 저장하거나, '수정' 버튼을 이용해주세요.")
            return

        properties = get_properties_payload()
        payload = {"parent": {"database_id": NOTION_DB_ID}, "properties": properties}
        res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
        res.raise_for_status()
        new_page_id = res.json().get("id")

        if new_page_id:
            save_loan_items(new_page_id)
        
        fetch_all_notion_customers()
        st.success(f"✅ '{customer_name}' 고객 정보가 Notion에 새로 저장되었습니다.")

    except Exception as e:
        st.error(f"❌ 신규 저장 실패: {e}")

def update_existing_customer():
    """[신규] 기존 고객 정보를 수정(덮어쓰기)하는 함수"""
    customer_name = st.session_state.get("customer_name", "").strip()
    if not customer_name:
        st.error("고객명이 입력되지 않았습니다.")
        return

    existing_customer_data = st.session_state.get("notion_customers", {}).get(customer_name)
    if not existing_customer_data:
        st.warning(f"'{customer_name}' 이름의 기존 고객을 찾을 수 없습니다. 신규 저장을 이용해주세요.")
        return
    
    page_id = existing_customer_data.get("notion_page_id")

    try:
        properties = get_properties_payload()
        update_url = f"https://api.notion.com/v1/pages/{page_id}"
        res = requests.patch(update_url, headers=NOTION_HEADERS, json={"properties": properties})
        res.raise_for_status()

        save_loan_items(page_id)
        
        fetch_all_notion_customers()
        st.success(f"✅ '{customer_name}' 고객 정보가 성공적으로 수정되었습니다.")

    except Exception as e:
        st.error(f"❌ 수정 실패: {e}")


def delete_customer_from_notion(customer_name):
    """기존 고객 정보를 삭제하는 함수"""
    customer_data = st.session_state.get("notion_customers", {}).get(customer_name)
    if not customer_data or "notion_page_id" not in customer_data:
        st.error("삭제할 고객을 찾을 수 없습니다.")
        return
    
    page_id = customer_data["notion_page_id"]
    try:
        # 연결된 대출 항목들 보관
        loan_query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID_LOAN}/query"
        payload = {"filter": {"property": LOAN_DB_RELATION_PROPERTY_NAME, "relation": {"contains": page_id}}}
        res = requests.post(loan_query_url, headers=NOTION_HEADERS, json=payload)
        res.raise_for_status()
        for page in res.json().get("results", []):
            archive_url = f"https://api.notion.com/v1/pages/{page['id']}"
            requests.patch(archive_url, headers=NOTION_HEADERS, json={"archived": True})

        # 고객 정보 보관
        customer_archive_url = f"https://api.notion.com/v1/pages/{page_id}"
        requests.patch(customer_archive_url, headers=NOTION_HEADERS, json={"archived": True})
        
        st.success(f"✅ '{customer_name}' 고객 및 관련 대출 항목이 모두 삭제(보관)되었습니다.")
        fetch_all_notion_customers()
    except Exception as e:
        st.error(f"❌ 고객 삭제 실패: {e}")
# --- [개선된 history_manager.py 코드 끝] ---
