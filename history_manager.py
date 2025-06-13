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
}# ───────────────────────────────────────────────
# 🔑 Notion → 세션 키 매핑
# ───────────────────────────────────────────────

KEY_MAP = {
    "고객명": "customer_name",
    "주소": "address_input",
    "지역": "region",
    "방공제": "manual_d",
    "KB시세": "raw_price_input",
    "전용면적": "area_input",
    "층수": "extracted_floor",
    "LTV비율": "ltv_selected",
    "수수료": "total_fee_text",
    "대출항목": "loan_summary",
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
    
        # 1️⃣ 동일 고객명(고객명+생년월일) 존재 시, 덮어쓸지 먼저 물어보기
    query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    query_payload = {
        "filter": {
            "property": "고객명",
            "title": {"equals": customer_name}
        }
    }
    res = requests.post(query_url, headers=NOTION_HEADERS, json=query_payload)
    results = res.json().get("results", [])



    # 이미 존재하면 덮어쓸지 묻고, 확인해야 진행
    
    if results and not st.session_state.get("save_action", ""):
        col_over, col_add = st.columns(2)
        with col_over:
            if st.button("⚠️ 동일 고객명 데이터가 이미 있습니다. [덮어쓰기]"):
                st.session_state["save_action"] = "overwrite"
                st.experimental_rerun()
        with col_add:
            if st.button("➕ 동일 고객명 데이터가 이미 있습니다. [추가저장]"):
                st.session_state["save_action"] = "add"
                st.experimental_rerun()
        st.warning("❗ 동일한 고객명이 이미 존재합니다. 덮어쓸지([덮어쓰기]) 또는 새로 추가저장([추가저장])할지 선택하세요.")
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
# 기존 페이지 삭제(archive) → ❌ 하지마!
# 대신, 기존 페이지 있으면 PATCH(수정)만 해!

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
        
        if results:
            # PATCH: 기존 고객명 있으면 덮어쓰기
            page_id = results[0]["id"]
            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            requests.patch(update_url, headers=NOTION_HEADERS, json={
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
            })
            customer_page_id = page_id
        else:
            # POST: 없으면 새로 생성
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
            res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
            customer_page_id = res.json().get("id")
    except Exception as e:
        st.error(f"❌ 저장 중 오류: {e}")
        return


        # 기존 대출항목 모두 삭제(archive)
    loan_query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID_LOAN}/query"
    loan_query_payload = {
        "filter": {
            "property": "고객",
            "relation": {
                "contains": customer_page_id
            }
        }
    }
    loan_res = requests.post(loan_query_url, headers=NOTION_HEADERS, json=loan_query_payload)
    loan_results = loan_res.json().get("results", [])

    for loan_page in loan_results:
        loan_page_id = loan_page["id"]
        del_url = f"https://api.notion.com/v1/pages/{loan_page_id}"
        requests.patch(del_url, headers=NOTION_HEADERS, json={"archived": True})    


    # 2️⃣ 대출항목 저장 (전부 성공해야만 최종 성공 표시)
    all_success = True

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
                "고객명": {"title": [{"text": {"content": data["고객명"]}}]},
                "설정자": {"rich_text": [{"text": {"content": lender}}]},   # ← 이 한 줄 추가!
                "채권최고액": {"number": int(maxamt or 0)},
                "설정비율": {"number": int(ratio or 0)},
                "원금": {"number": int(principal or 0)},
                "진행구분": {"select": {"name": status}},
                "고객": {"relation": [{"id": customer_page_id}]}
            }
        }
        try:
            loan_res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=loan_payload)
            if not loan_res.ok:
                st.error(f"❌ 대출항목 {i+1} 저장 실패: {loan_res.text}")
                all_success = False
        except Exception as e:
            st.error(f"❌ 대출항목 {i+1} 저장 중 예외: {e}")
            all_success = False

    if all_success:
        st.success("✅ 고객 + 대출항목 저장 완료")
    else:
        st.error("❌ 일부 또는 전체 대출항목 저장 실패! 오류 메시지 참조")


def delete_customer_from_notion(customer_name):
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
    except Exception as e:
        st.error(f"❌ 고객 삭제 실패: {e}")
