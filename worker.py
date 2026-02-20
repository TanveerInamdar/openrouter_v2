import uuid
import json

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


class WebhookPayload(BaseModel):
    record: dict


def process_message(msg_id: int, current_session_id: uuid.UUID):
    try:
        # Get full chat history for context
        history = get_chat_history(current_session_id)

        # Get model and title for this session
        session_metadata = supabase.table("sessions").select("model, title").eq("session_id", current_session_id).single().execute()
        model_name = session_metadata.data["model"]
        print(model_name)

        # Build query list for OpenRouter from history
        query = [{"role": msg["role"].lower(), "content": msg["content"]} for msg in history]
        result = model_chat(query, model_name)
        print("Called API with model: ", model_name)

        # Mark user message Completed and insert assistant response
        if result != "ERROR":
            update_message_state(msg_id, "Completed")
            send_message_to_db(current_session_id, "assistant", result, "Completed")
            print(f"Worker Completed for message id {msg_id}")
        else:
            update_message_state(msg_id, "Failed")
            print(f"Worker Failed for message id {msg_id}")

        # Title generation
        title_result = session_metadata.data["title"]
        print(f"Current title: {title_result}")
        if title_result == "New Chat" and result != "ERROR":
            x = new_chat(result)
            update_session_title(current_session_id, x)
            print("title changed to ", x)

    except Exception as e:
        print(f"ERROR: {e}")
        update_message_state(msg_id, "Failed")


@app.post("/process-message")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    record = payload.record

    # Only process Pending messages
    if record.get("state") != "Pending":
        return {"status": "skipped"}

    msg_id = record["id"]
    current_session_id = record["session_id"]
    print(f"Webhook received for message id {msg_id} and session id {current_session_id}")

    background_tasks.add_task(process_message, msg_id, current_session_id)
    return {"status": "ok"}


# ── REST endpoints for the frontend ─────────────────────────────────────────

@app.get("/models")
def list_models():
    from model_list import final_models
    final_models.sort()
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
def delete_session(session_id: str):
    supabase.table("messages").delete().eq("session_id", session_id).execute()
    supabase.table("sessions").delete().eq("session_id", session_id).execute()
    return {"status": "deleted"}


@app.get("/history/{session_id}")
def chat_history(session_id: str):
    msgs = get_chat_history(session_id) or []
    return {"messages": msgs}


# ── WebSocket chat endpoint ──────────────────────────────────────────────────

def process_message_ws(msg_id: int, current_session_id: str, ws_send_callback):
    """Synchronous worker — runs in a background thread via BackgroundTasks."""
    try:
        history = get_chat_history(current_session_id)
        session_meta = supabase.table("sessions").select("model, title").eq("session_id", current_session_id).single().execute()
        model_name = session_meta.data["model"]

        query = [{"role": m["role"].lower(), "content": m["content"]} for m in history]
        result = model_chat(query, model_name)

        if result != "ERROR":
            update_message_state(msg_id, "Completed")
            send_message_to_db(current_session_id, "assistant", result, "Completed")
        else:
            update_message_state(msg_id, "Failed")
            ws_send_callback({"type": "error", "message": "Model returned an error."})
            return

        # Title generation
        current_title = session_meta.data["title"]
        new_title = current_title
        if current_title == "New Chat":
            new_title = new_chat(result)
            update_session_title(current_session_id, new_title)

        ws_send_callback({"type": "message", "role": "assistant", "content": result, "title": new_title})

    except Exception as e:
        print(f"WS Worker ERROR: {e}")
        update_message_state(msg_id, "Failed")
        ws_send_callback({"type": "error", "message": str(e)})


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    print(f"WS connected: {session_id}")

    # Buffer for outgoing messages from the background thread
    import asyncio
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def enqueue(payload: dict):
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    async def sender():
        while True:
            msg = await queue.get()
            if msg is None:
                break
            await websocket.send_text(json.dumps(msg))

    sender_task = asyncio.create_task(sender())

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "model_change":
                update_session_model(session_id, data["model"])
                continue

            if data.get("type") == "message":
                content = data.get("content", "").strip()
                model   = data.get("model", "openai/gpt-4.1-mini")
                if not content:
                    continue

                # Ensure session exists
                existing = supabase.table("sessions").select("session_id").eq("session_id", session_id).execute()
                if not existing.data:
                    create_session(session_id, "New Chat", model)
                else:
                    update_session_model(session_id, model)

                # Persist user message
                db_res = send_message_to_db(session_id, "User", content, "Pending")
                msg_id = db_res.data[0]["id"] if db_res and db_res.data else None

                if msg_id is None:
                    await websocket.send_text(json.dumps({"type": "error", "message": "DB error saving message"}))
                    continue

                # Run model call in thread pool so we don't block the event loop
                import concurrent.futures
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                loop.run_in_executor(executor, process_message_ws, msg_id, session_id, enqueue)

    except WebSocketDisconnect:
        print(f"WS disconnected: {session_id}")
    finally:
        queue.put_nowait(None)
        await sender_task
