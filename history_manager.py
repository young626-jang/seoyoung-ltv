import os
import re
import pandas as pd
import streamlit as st
from datetime import datetime
from ast import literal_eval
import requests

NOTION_TOKEN = "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"
NOTION_DB_ID = "20eebdf1-11b5-80ad-9004-c7e82d290cbc"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

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

def get_customer_options():
    return list(st.session_state.get("notion_customers", {}).keys())

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

def load_customer_input(customer_name):
    data = st.session_state.get("notion_customers", {}).get(customer_name)
    if not data:
        st.warning("📭 불러올 데이터가 없습니다.")
        return

    for key, val in data.items():
        if key == "raw_price_input":
            val = "{:,}".format(int(val)) if isinstance(val, int) else str(val)
            st.session_state["raw_price_input_default"] = val
            continue
        if key == "raw_price":
            val = "{:,}".format(int(val)) if isinstance(val, int) else str(val)
        st.session_state[key] = val

    # ✅ 저장된 결과 내용만 복원
    if "text_to_copy" in data:
        st.session_state["text_to_copy"] = data["text_to_copy"]

def delete_customer_from_notion(customer_name: str):
    if not customer_name:
        st.warning("❗ 고객명이 비어 있습니다.")
        return
    try:
        query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
        query_payload = {
            "filter": {
                "property": "고객명",
                "title": {
                    "equals": customer_name
                }
            }
        }
        res = requests.post(query_url, headers=NOTION_HEADERS, json=query_payload)
        results = res.json().get("results", [])
        if not results:
            st.info("📭 Notion에 해당 고객명이 존재하지 않습니다.")
            return
        for page in results:
            page_id = page["id"]
            del_url = f"https://api.notion.com/v1/pages/{page_id}"
            requests.patch(del_url, headers=NOTION_HEADERS, json={"archived": True})
        st.success(f"🗑️ Notion에서 '{customer_name}' 정보가 삭제되었습니다.")
    except Exception as e:
        st.error(f"❌ 삭제 실패: {e}")

def save_user_input():
    customer_name = st.session_state.get("customer_name", "").strip()
    if not customer_name:
        return

    data = {
        "고객명": customer_name,
        "주소": st.session_state.get("address_input", ""),
        "지역": st.session_state.get("region", ""),
        "방공제": int(re.sub(r"[^\d]", "", str(st.session_state.get("manual_d", "0"))) or 0),
        "KB시세": int(re.sub(r"[^\d]", "", str(st.session_state.get("raw_price_input", "0"))) or 0),
        "전용면적": st.session_state.get("area_input", ""),
        "층수": st.session_state.get("extracted_floor", 0),
        "LTV비율": ", ".join([str(l) for l in st.session_state.get("ltv_selected", [])]),
        "수수료": st.session_state.get("total_fee_text", ""),
        "대출항목": "",
        "저장시각": datetime.now().isoformat(),
        "메모": st.session_state.get("text_to_copy", "")
    }

    rows = int(st.session_state.get("rows", 0))
    loan_summary = []
    for i in range(rows):
        item = {
            "설정자": st.session_state.get(f"lender_{i}", ""),
            "채권최고액": st.session_state.get(f"maxamt_{i}", ""),
            "비율": st.session_state.get(f"ratio_{i}", ""),
            "원금": st.session_state.get(f"principal_{i}", ""),
            "진행": st.session_state.get(f"status_{i}", ""),
        }
        if item["설정자"]:
            line = f"{item['설정자']} | 최고액: {item['채권최고액']} | 비율: {item['비율']}% | 원금: {item['원금']} | {item['진행']}"
            loan_summary.append(line)
    data["대출항목"] = "\n".join(loan_summary)

    try:
        query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
        query_payload = {
            "filter": {
                "property": "고객명",
                "title": {
                    "equals": customer_name
                }
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

    try:
        payload = {
            "parent": {"database_id": NOTION_DB_ID},
            "properties": {
                "고객명": {"title": [{"text": {"content": data["고객명"]}}]},
                "주소": {"rich_text": [{"text": {"content": data["주소"]}}]},
                "지역": {"rich_text": [{"text": {"content": data["지역"]}}]},
                "방공제": {"number": data["방공제"]},
                "KB시세": {"number": data["KB시세"]},
                "전용면적": {"rich_text": [{"text": {"content": data["전용면적"]}}]},
                "층수": {"number": int(data["층수"] or 0)},
                "LTV비율": {"rich_text": [{"text": {"content": data["LTV비율"]}}]},
                "수수료": {"rich_text": [{"text": {"content": data["수수료"]}}]},
                "대출항목": {"rich_text": [{"text": {"content": data["대출항목"]}}]},
                "저장시각": {"date": {"start": data["저장시각"]}},
                "메모": {"rich_text": [{"text": {"content": data["메모"]}}]}
            }
        }
        res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
        if res.status_code == 200:
            st.success("✅ Notion 저장 완료")
        else:
            st.error(f"❌ Notion 저장 실패: {res.text}")
    except Exception as e:
        st.error(f"❌ Notion 요청 오류: {str(e)}")
