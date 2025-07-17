# streamlit_app.py
import glob
import pathlib
import threading
import requests

import streamlit as st
from openai import OpenAI

# FastAPI for webhook endpoint
from fastapi import FastAPI, Request
import uvicorn

### ─── 1) FASTAPI WEBHOOK SERVER ─────────────────────────────────────────────
#
# n8n POST any new batch of messages (or file paths)
#    URL: http://<streamlit‐host>:8000/n8n_webhook
# Payload can be e.g. { "file_path": "/data/messenger/2025-07-14/12345.txt" }
# clear cache so that load_corpus() will reload from disk.
#
webhook_app = FastAPI()

@webhook_app.post("/n8n_webhook")
async def n8n_webhook(req: Request):
    payload = await req.json()
    # inspect payload["file_path"] or payload["messages"] here
    load_corpus.clear()
    return {"status": "cache_cleared"}

def run_webhook_server():
    uvicorn.run(webhook_app, host="0.0.0.0", port=8000)

# start FastAPI 
threading.Thread(target=run_webhook_server, daemon=True).start()


### OPENAI CLIENT & CORPUS LOADING

client = OpenAI()

@st.cache_data(show_spinner=False)
def load_corpus(folder="data/messenger"):
    """Read all .txt files under data/messenger and return a dict of {conv_id: text}."""
    corpus = {}
    for fp in glob.glob(f"{folder}/**/*.txt", recursive=True):
        cid = pathlib.Path(fp).stem
        text = pathlib.Path(fp).read_text(encoding="utf-8")
        corpus[cid] = text
    return corpus


### HELPER TO TRIGGER YOUR N8N WORKFLOW 

def trigger_n8n_workflow(user_message: str) -> bool:
    """
    Send the new user message to n8n's trigger webhook.
    In n8n you have a Webhook node listening on /trigger-workflow
    that starts your pipeline.
    """
    try:
        resp = requests.post(
            "http://n8n:5678/webhook/trigger-workflow",
            json={"message": user_message},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


### STREAMLIT CHAT UI 
st.title("💬 CSKH Chatbot (VN)")

if "history" not in st.session_state:
    st.session_state.history = []

# display past chat
for msg in st.session_state.history:
    st.chat_message(msg["role"]).write(msg["content"])

# new user input
user_input = st.chat_input("Hỏi tôi bất cứ điều gì về khách hàng")

if user_input:
    # 1) Add user message to history
    st.session_state.history.append({"role": "user", "content": user_input})

    # 2) Trigger your n8n pipeline
    ok = trigger_n8n_workflow(user_input)
    if not ok:
        st.error("Không thể kích hoạt workflow n8n. Vui lòng kiểm tra URL/ mạng.")

    # 3) Prepare context for GPT
    corpus = load_corpus()  # may reload if webhook was just called
    # naive: top-20 convos; for production swap in vector search
    docs = "\n\n".join(list(corpus.values())[:20])

    system = (
        "Bạn là trợ lý phân tích CSKH. "
        "Tất cả dữ liệu đều bằng tiếng Việt. "
        "Phân loại sentiment (Positive|Neutral|Negative) "
        "và trả lời câu hỏi của user."
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": docs + "\n\n---\n\nCâu hỏi: " + user_input},
        ],
        temperature=0.2,
    )
    answer = resp.choices[0].message.content

    # 4) Show GPT answer
    st.session_state.history.append({"role": "assistant", "content": answer})
    st.experimental_rerun()