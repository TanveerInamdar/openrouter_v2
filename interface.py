import streamlit as st
import uuid
import random
import time
from model_list import final_models
from db_init import send_message_to_db, get_chat_history, create_session, update_session_model, get_sessions, supabase


if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
current_session_id = st.session_state.session_id

st.set_page_config(layout="wide")
st.markdown(
    """
    <style>
    /* Adjust the maximum width of the main content area */
    .block-container {
        max-width: 68rem;
        padding-top: 2rem;
        padding-right: 5rem;
        padding-left: 5rem;
    }
    /* Target the container for st.chat_input */
    [data-testid="stChatInput"] {
        max-width: 58.10rem;
        margin-left: auto;
        margin-right: auto;
        left: 0;
        right: 0;
    }

    .stChatInputContainer {
        padding-left: 20px !important;
        padding-right: 20px !important;
    }
    </style>
    """,

    unsafe_allow_html=True
)
welcome_statements = ["Hey Tan, what's on your mind? ", "Hello, Tanveer", "What's up", "Greetings!", "Howdy!"]
x = random.choice(welcome_statements)

st.title(f"{x}")

# Load chat history and current model for this session
history = get_chat_history(current_session_id)
rows = [(msg["role"], msg["content"]) for msg in history] if history else []

current_model = 'openai/gpt-oss-20b:free'
session_metadata = supabase.table("sessions").select("model").eq("session_id", current_session_id).execute()
if session_metadata.data and session_metadata.data[0]["model"]:
    current_model = session_metadata.data[0]["model"]

with st.sidebar:

    if model_choice := st.selectbox(
            "What model should we use?",
            final_models,
            index=None,
            placeholder=f"{current_model} model",
            key=f"model_select_{current_session_id}"

    ):
        st.write("You selected:", model_choice)
        update_session_model(current_session_id, model_choice)
        print("Updated Model Choice: ", model_choice)
        current_model = model_choice
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear current chat"):
            supabase.table("sessions").delete().eq("session_id", current_session_id).execute()
            supabase.table("messages").delete().eq("session_id", current_session_id).execute()
            st.rerun()
    with col2:
        if st.button("New Chat"):
            st.session_state.session_id = str(uuid.uuid4())
            current_session_id = st.session_state.session_id
            st.rerun(scope="app")

    st.divider()
    st.title("Past Chats")
    st.divider()

    past_sessions = get_sessions()
    for session in past_sessions:
        if st.button(label=session["title"], key=session["session_id"]):
            st.session_state.session_id = session["session_id"]
            st.rerun()

for row in rows:
    st.chat_message(row[0]).write(row[1])

latest_state = history[-1]["state"] if history else None

if latest_state == "Pending":
    print("Pending API call detected. Started Pending answer workflow")
    with st.spinner("Hold on..."):
        while True:
            fresh_history = get_chat_history(current_session_id)
            if fresh_history and fresh_history[-1]["state"] != "Pending":
                break
            time.sleep(0.5)
        st.rerun()

provider, slash, cleaned_model_name = current_model.partition("/")
if prompt := st.chat_input(f"Talking to {cleaned_model_name}"):
    if not history:
        create_session(current_session_id, "New Chat", current_model)
    print("Updated AI Model: ", current_model)
    send_message_to_db(current_session_id, "User", prompt, "Pending")

    st.chat_message("User").write(prompt)
    with st.spinner("Hold on..."):
        while True:
            fresh_history = get_chat_history(current_session_id)
            if fresh_history and fresh_history[-1]["state"] == "Completed":
                break
            time.sleep(0.5)
        st.rerun()



