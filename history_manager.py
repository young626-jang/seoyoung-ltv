import os
import re
import pandas as pd
import streamlit as st
from datetime import datetime
from ast import literal_eval
import requests

# ─────────────────────────────
# 🔐 Notion API 설정
# ─────────────────────────────

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
# ───────────────────────────────────────────────
# 🔑 Notion → 세션 키 매핑
# ───────────────────────────────────────────────

KEY_MAP = {
    "고객명": "customer_name",
    "주소": "address_input",
    "방공제 지역": "region",
    "방공제 금액": "manual_d",
    "KB시세": "raw_price_input",
    "전용면적": "area_input",
    "LTV비율1": "ltv1",
    "LTV비율2": "ltv2",
    "메모": "text_to_copy"
}


# ─────────────────────────────
# 🔢 시세 변환 함수 (한글 입력 → 숫자)
# ─────────────────────────────
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

# ─────────────────────────────
# 🧾 고객 목록 반환
# ─────────────────────────────
def get_customer_options():
    return list(st.session_state.get("notion_customers", {}).keys())

# ─────────────────────────────
# 🧲 Notion → 전체 고객 정보 불러오기
# ─────────────────────────────
def fetch_all_notion_customers():
    notion_customers = {}
    try:
        query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
        has_more = True
        next_cursor = None
        while has_more:
            payload = {"page_size": 100}
            if next_cursor:
                payload["start_cursor"] = next_cursor
            res = requests.post(query_url, headers=NOTION_HEADERS, json=payload)
            res.raise_for_status()
            data = res.json()
            for page in data.get("results", []):
                props = page.get("properties", {})
                customer = {}
                notion_name = props.get("고객명", {}).get("title", [])
                if notion_name:
                    customer_name = notion_name[0]["text"]["content"]
                    for key, app_key in KEY_MAP.items():
                        if key in props:
                            value = props[key]
                            if "rich_text" in value:
                                customer[app_key] = value["rich_text"][0]["text"]["content"] if value["rich_text"] else ""
                            elif "number" in value:
                                customer[app_key] = value["number"]
                            elif "date" in value:
                                customer[app_key] = value["date"]["start"]
                            elif "title" in value:
                                customer[app_key] = value["title"][0]["text"]["content"]
                    notion_customers[customer_name] = customer
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
    except Exception as e:
        st.warning(f"❗ Notion 데이터 조회 실패: {e}")
    st.session_state["notion_customers"] = notion_customers

# ─────────────────────────────
# 📥 고객 정보 불러오기
# ─────────────────────────────

# 파이트 파일에서 불러오기

def load_customer_input(customer_name):
    data = st.session_state.get("notion_customers", {}).get(customer_name)
    if not data:
        st.warning("포토 데이터가 없습니다.")
        return

    for key, val in data.items():
        if key == "raw_price_input":
            val = "{:,}".format(int(val)) if isinstance(val, int) else str(val)
            st.session_state["raw_price_input_default"] = val
            continue
        if key == "raw_price":
            val = "{:,}".format(int(val)) if isinstance(val, int) else str(val)

        app_key = KEY_MAP.get(key, key)
        st.session_state[app_key] = val

    # ◼ LTV비율1, 2 등 발전시 ltv_selected 모델에도 추가
    ltv1 = st.session_state.get("ltv1", "")
    ltv2 = st.session_state.get("ltv2", "")
    ltv_selected = []
    for val in [ltv1, ltv2]:
        try:
            v = int(val)
            if 1 <= v <= 100:
                ltv_selected.append(v)
        except:
            pass
    st.session_state["ltv_selected"] = list(dict.fromkeys(ltv_selected))

    # 만약 메모가 있으면 복원
    if "text_to_copy" in data:
        st.session_state["text_to_copy"] = data["text_to_copy"]
    
# ─────────────────────────────
# 💾 고객 정보 저장
# ─────────────────────────────
def save_user_input():
    customer_name = st.session_state.get("customer_name", "").strip()
    if not customer_name:
        return

    # LTV 두 개 분리 저장
    ltv1 = st.session_state.get("ltv1", "").strip()
    ltv2 = st.session_state.get("ltv2", "").strip()

    data = {
        "고객명": customer_name,
        "주소": st.session_state.get("address_input", ""),
        "방공제 지역": st.session_state.get("region", ""),
        "방공제 금액": int(re.sub(r"[^\d]", "", str(st.session_state.get("manual_d", "0"))) or 0),
        "KB시세": int(re.sub(r"[^\d]", "", str(st.session_state.get("raw_price_input", "0"))) or 0),
        "전용면적": st.session_state.get("area_input", ""),
        "LTV비율1": ltv1,
        "LTV비율2": ltv2,
        "메모": st.session_state.get("text_to_copy", ""),
        "저장시각": datetime.now().isoformat(),
    }

    # 기존 페이지 삭제
    try:
        query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
        query_payload = {
            "filter": {
                "property": "고객명",
                "title": {"equals": customer_name}
            }
        }
        res = requests.post(query_url, headers=NOTION_HEADERS, json=query_payload)
        results = res.json().get("results", [])
        for page in results:
            page_id = page["id"]
            del_url = f"https://api.notion.com/v1/pages/{page_id}"
            requests.patch(del_url, headers=NOTION_HEADERS, json={"archived": True})
    except:
        pass

        # 새 페이지 생성 payload
        payload = {
            "parent": {"database_id": NOTION_DB_ID},
            "properties": {
                "고객명": {"title": [{"text": {"content": data["고객명"]}}]},
                "주소": {"rich_text": [{"text": {"content": data["주소"]}}]},
                "방공제 지역": {"rich_text": [{"text": {"content": data["방공제 지역"]}}]},
                "방공제 금액": {"number": data["방공제 금액"]},
                "KB시세": {"number": data["KB시세"]},
                "전용면적": {"rich_text": [{"text": {"content": data["전용면적"]}}]},
                "LTV비율1": {"rich_text": [{"text": {"content": data["LTV비율1"]}}]},
                "LTV비율2": {"rich_text": [{"text": {"content": data["LTV비율2"]}}]},
                "메모": {"rich_text": [{"text": {"content": data["메모"]}}]},
                "저장시각": {"date": {"start": data["저장시각"]}}
            }
        }

        # 고객 저장
        try:
            res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
            if res.status_code != 200:
                st.error(f"❌ 고객 저장 실패: {res.text}")
                return
        except Exception as e:
            st.error(f"❌ 예외 발생: {e}")
            return

        customer_page_id = res.json().get("id")
        if not customer_page_id:
            st.error("❌ 고객 ID 추출 실패")
            return

        # 2️⃣ 대출항목 리스트 저장
        rows = int(st.session_state.get("rows", 0) or 0)
        for i in range(rows):
            lender = st.session_state.get(f"lender_{i}", "")
            maxamt = re.sub(r"[^\d]", "", st.session_state.get(f"maxamt_{i}", "0"))
            ratio = re.sub(r"[^\d]", "", st.session_state.get(f"ratio_{i}", "0"))
            principal = re.sub(r"[^\d]", "", st.session_state.get(f"principal_{i}", "0"))
            status = st.session_state.get(f"status_{i}", "")

            if not lender:
                continue

            loan_payload = {
                "parent": {"database_id": NOTION_DB_ID_LOAN},
                "properties": {
                    "설정자": {"rich_text": [{"text": {"content": lender}}]},
                    "채권최고액": {"number": int(maxamt or 0)},
                    "설정비율": {"number": int(ratio or 0)},
                    "원금": {"number": int(principal or 0)},
                    "진행구분": {"select": {"name": status}},
                    "고객": {"relation": [{"id": customer_page_id}]}
                }
            }
            requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=loan_payload)

        st.success("✅ 고객 + 대출항목 저장 완료")
