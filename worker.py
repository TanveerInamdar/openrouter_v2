import uuid

from main import new_chat, model_chat
from db_init import send_message_to_db, get_chat_history, update_message_state, update_session_title, supabase
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

app = FastAPI()


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
