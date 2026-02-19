import os
from supabase import create_client, Client
from dotenv import load_dotenv
import uuid
load_dotenv()
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)
random_uuid = uuid.uuid4()
response = (
    supabase.table("sessions")
    .select("model")
    .execute()
)
print(response)


def send_message_to_db(session_id: uuid, role:str, message: str, state:str):
    try:
        response = (
            supabase.table("messages")
            .insert({
                "session_id": str(session_id),
                "role": role,
                "content": message,
                "state": state
            })
            .execute()
        )
        return response
    except Exception as E:
        print(E)
        return None


def get_chat_history(session_id: uuid):
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq("session_id", str(session_id))
            .order("created_at", desc=False)
            .execute()
        )
        return response.data
    except Exception as E:
        print(E)
        return None


def get_chat_titles():
    try:
        response = (
            supabase.table("sessions")
            .select("session_id")
            .execute()
        )
        # Extract just the session_id values into a list
        session_ids = [session["session_id"] for session in response.data]
        return session_ids
    except Exception as E:
        print(E)
        return None


def create_session(session_id: uuid, title: str, model: str):
    try:
        response = (
            supabase.table("sessions")
            .upsert({
                "session_id": str(session_id),
                "title": title,
                "model": model
            })
            .execute()
        )
        return response
    except Exception as E:
        print(E)
        return None


def update_session_title(session_id: uuid, title: str):
    try:
        response = (
            supabase.table("sessions")
            .update({"title": title})
            .eq("session_id", str(session_id))
            .execute()
        )
        return response
    except Exception as E:
        print(E)
        return None


def update_session_model(session_id: uuid, model: str):
    try:
        response = (
            supabase.table("sessions")
            .update({"model": model})
            .eq("session_id", str(session_id))
            .execute()
        )
        return response
    except Exception as E:
        print(E)
        return None


def update_message_state(message_id: int, state: str):
    try:
        response = (
            supabase.table("messages")
            .update({"state": state})
            .eq("id", message_id)
            .execute()
        )
        return response
    except Exception as E:
        print(E)
        return None