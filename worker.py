import uuid
import json
import asyncio

from main import new_chat, model_chat
from db_init import (
    send_message_to_db, get_chat_history, update_message_state,
    update_session_title, create_session, update_session_model,
    get_sessions, supabase
)
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

@app.get("/")
def serve_ui():
    return FileResponse("frontend/chat_interface.html")


# ── Connection registry ──────────────────────────────────────────────────────
# Maps session_id -> (WebSocket, asyncio event loop)
# Used by the webhook to push responses back to the right browser tab
active_connections: dict[str, tuple[WebSocket, asyncio.AbstractEventLoop]] = {}


# ── Webhook handler (called by Supabase on new Pending message) ──────────────

class WebhookPayload(BaseModel):
    record: dict


def process_message(msg_id: int, current_session_id: str):
    try:
        history = get_chat_history(current_session_id)

        session_metadata = supabase.table("sessions").select("model, title").eq("session_id", current_session_id).single().execute()
        model_name = session_metadata.data["model"]
        print(f"Processing with model: {model_name}")

        query = [{"role": msg["role"].lower(), "content": msg["content"]} for msg in history]
        result = model_chat(query, model_name)
        print("Called API with model: ", model_name)

        if result != "ERROR":
            update_message_state(msg_id, "Completed")
            send_message_to_db(current_session_id, "assistant", result, "Completed")
            print(f"Worker Completed for message id {msg_id}")
        else:
            update_message_state(msg_id, "Failed")
            print(f"Worker Failed for message id {msg_id}")
            _push_to_ws(current_session_id, {"type": "error", "message": "Model returned an error."})
            return

        # Title generation
        title_result = session_metadata.data["title"]
        new_title = title_result
        print(f"Current title: {title_result}")
        if title_result == "New Chat":
            new_title = new_chat(result)
            update_session_title(current_session_id, new_title)
            print("Title changed to:", new_title)

        _push_to_ws(current_session_id, {
            "type": "message",
            "role": "assistant",
            "content": result,
            "title": new_title
        })

    except Exception as e:
        print(f"ERROR: {e}")
        update_message_state(msg_id, "Failed")
        _push_to_ws(current_session_id, {"type": "error", "message": str(e)})


def _push_to_ws(session_id: str, payload: dict):
    """Thread-safe: push a message to the WebSocket for this session if connected."""
    entry = active_connections.get(session_id)
    if not entry:
        print(f"No active WS for session {session_id}, skipping push")
        return
    ws, loop = entry
    asyncio.run_coroutine_threadsafe(ws.send_text(json.dumps(payload)), loop)


@app.post("/process-message")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    record = payload.record

    if record.get("state") != "Pending":
        return {"status": "skipped"}

    msg_id = record["id"]
    current_session_id = record["session_id"]
    print(f"Webhook received for message id {msg_id} and session id {current_session_id}")

    background_tasks.add_task(process_message, msg_id, current_session_id)
    return {"status": "ok"}


# ── REST endpoints ───────────────────────────────────────────────────────────

@app.get("/models")
def list_models():
    from model_list import final_models
    return {"models": final_models}


@app.get("/sessions")
def list_sessions():
    return {"sessions": get_sessions()}


@app.get("/session/{session_id}")
def get_session(session_id: str):
    res = supabase.table("sessions").select("*").eq("session_id", session_id).execute()
    if res.data:
        return res.data[0]
    return {}


@app.delete("/session/{session_id}")
def delete_session_route(session_id: str):
    supabase.table("messages").delete().eq("session_id", session_id).execute()
    supabase.table("sessions").delete().eq("session_id", session_id).execute()
    return {"status": "deleted"}


@app.get("/history/{session_id}")
def chat_history(session_id: str):
    msgs = get_chat_history(session_id) or []
    return {"messages": msgs}


class SendMessagePayload(BaseModel):
    session_id: str
    content: str
    model: str = "openai/gpt-4.1-mini"


@app.post("/send-message")
def send_message_route(payload: SendMessagePayload):
    """
    Frontend calls this to save a user message as Pending.
    Supabase webhook then fires /process-message to handle it.
    """
    existing = supabase.table("sessions").select("session_id").eq("session_id", payload.session_id).execute()
    if not existing.data:
        create_session(payload.session_id, "New Chat", payload.model)
    else:
        update_session_model(payload.session_id, payload.model)

    db_res = send_message_to_db(payload.session_id, "User", payload.content, "Pending")
    if not db_res or not db_res.data:
        return {"status": "error", "message": "Failed to save message"}

    msg_id = db_res.data[0]["id"]
    print(f"Message saved with id {msg_id} for session {payload.session_id}")
    return {"status": "ok", "msg_id": msg_id}


# ── WebSocket — receive-only, used to push responses back to browser ─────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    active_connections[session_id] = (websocket, loop)
    print(f"WS connected: {session_id}")

    try:
        while True:
            # Keep connection alive; handle model change notifications from frontend
            raw = await websocket.receive_text()
            data = json.loads(raw)
            if data.get("type") == "model_change":
                update_session_model(session_id, data["model"])

    except WebSocketDisconnect:
        print(f"WS disconnected: {session_id}")
    finally:
        active_connections.pop(session_id, None)
