import streamlit as st
import sys
import os
from pathlib import Path
import time
from typing import Optional
import json
import uuid
import httpx

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from data.extract_sleeper_data import main as extract_data

LANGGRAPH_SERVER_URL = os.getenv("LANGGRAPH_SERVER_URL")
SUPABASE_KEY=os.getenv("SUPABASE_KEY", None)
SUPABASE_URL=os.getenv("SUPABASE_API_URL", None)

def _load_base_system_prompt() -> str:
    """
    Load the canonical system prompt markdown from the prompts package.

    Note: in your repo this file is `buddy/prompts/buddy.md` (you referred to it as prompt.md).
    """
    prompt_path = project_root / "buddy" / "prompts" / "buddy.md"
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        # If anything goes wrong, fall back to empty and still include user context.
        return ""

def _build_user_context_system_prompt(username: str | None, league_id: str | None) -> str:
    username_str = (username or "").strip() or "unknown"
    league_id_str = (league_id or "").strip() or "unknown"
    return (
        "Context for this conversation:\n"
        f"- User: {username_str}\n"
        f"- Sleeper league_id: {league_id_str}\n\n"
        "You should tailor answers, SQL queries, and analysis to this league_id's data in the database "
        "and communicate as if you are assisting this specific user."
    )


def _lg_process_line(line: str, current_event: str) -> str | None:
    """Parse one SSE line from LangGraph /runs/stream into printable text chunks."""
    if not line.startswith("data: "):
        return None
    data_content = line[6:]
    if current_event != "messages":
        return None

    message_chunk, metadata = json.loads(data_content)

    if message_chunk.get("type") == "AIMessageChunk":
        rm = message_chunk.get("response_metadata") or {}
        if rm.get("finish_reason") == "tool_calls":
            return "\n\n"

        tool_call_chunks = message_chunk.get("tool_call_chunks") or []
        if tool_call_chunks:
            return None

        return message_chunk.get("content", "")
    return None


def _lg_create_thread(user_id: str) -> dict:
    if not LANGGRAPH_SERVER_URL:
        raise RuntimeError("LANGGRAPH_SERVER_URL is not set.")
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            url=f"{LANGGRAPH_SERVER_URL}/threads",
            json={
                "thread_id": str(uuid.uuid4()),
                "metadata": {"user_id": user_id},
                "if_exists": "do_nothing",
            },
        )
        resp.raise_for_status()
        return resp.json()


def _lg_stream(thread_id: str, message: str, *, username: str | None, league_id: str | None):
    """Yield assistant text chunks from LangGraph server streaming endpoint."""
    if not LANGGRAPH_SERVER_URL:
        raise RuntimeError("LANGGRAPH_SERVER_URL is not set.")

    base_prompt = _load_base_system_prompt()
    user_context = _build_user_context_system_prompt(username=username, league_id=league_id)
    system_prompt = (base_prompt.strip() + "\n\n" + user_context.strip()).strip()
    current_event: str | None = None
    with httpx.Client(timeout=60.0) as client:
        with client.stream(
            "POST",
            url=f"{LANGGRAPH_SERVER_URL}/threads/{thread_id}/runs/stream",
            json={
                "assistant_id": "buddy",
                "input": {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "human", "content": message},
                    ]
                },
                "stream_mode": "messages-tuple",
            },
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                    continue
                chunk = _lg_process_line(line, current_event or "")
                if chunk:
                    yield chunk

# Page configuration
st.set_page_config(
    page_title="My Sleeper Buddy",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    :root {
        --sleeper-bg: #0b1220;          /* deep navy */
        --sleeper-surface: #121a2b;     /* slightly lighter */
        --sleeper-surface-2: #18233a;   /* hover/alt */
        --sleeper-text: #e7ecf5;        /* near-white */
        --sleeper-muted: #a9b4c7;       /* muted text */
        --sleeper-accent: #18e77c;      /* neon green */
        --sleeper-accent-2: #12c968;    /* darker neon */
        --sleeper-border: rgba(231, 236, 245, 0.10);
    }

    /* App background */
    .stApp {
        background: radial-gradient(1200px 800px at 20% 0%, rgba(24, 231, 124, 0.10) 0%, rgba(11, 18, 32, 1) 55%) !important;
        color: var(--sleeper-text) !important;
    }

    /* Tighten top padding a bit */
    section.main > div { padding-top: 1.5rem; }

    /* Header */
    .main-header {
        text-align: center;
        padding: 20px 0;
        margin-bottom: 30px;
        color: var(--sleeper-text);
    }
    .logo-container {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 20px;
        margin-bottom: 20px;
    }

    /* Inputs / forms */
    div[data-baseweb="input"] > div,
    div[data-baseweb="textarea"] > div {
        background-color: var(--sleeper-surface) !important;
        border: 1px solid var(--sleeper-border) !important;
        color: var(--sleeper-text) !important;
    }
    input, textarea {
        color: var(--sleeper-accent) !important;
        caret-color: var(--sleeper-text) !important;
    }
    label, .stMarkdown, .stTextInput label, .stTextArea label {
        color: var(--sleeper-muted) !important;
    }

    /* Primary buttons */
    .stButton > button[kind="primary"] {
        background: linear-gradient(90deg, var(--sleeper-accent), var(--sleeper-accent-2)) !important;
        border: 0 !important;
        color: #06110a !important;
        font-weight: 700 !important;
        border-radius: 12px !important;
        padding: 0.6rem 1rem !important;
    }
    .stButton > button[kind="primary"]:hover {
        filter: brightness(1.05);
    }

    /* Secondary buttons */
    .stButton > button {
        background-color: var(--sleeper-surface) !important;
        border: 1px solid var(--sleeper-border) !important;
        color: var(--sleeper-text) !important;
        border-radius: 12px !important;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: var(--sleeper-surface) !important;
        border-right: 1px solid var(--sleeper-border) !important;
    }

    /* Progress bar accent */
    div[role="progressbar"] > div {
        background-color: var(--sleeper-accent) !important;
    }

    /* Chat bubbles (Streamlit native components) */
    div[data-testid="stChatMessage"] {
        border: 1px solid var(--sleeper-border);
        background-color: rgba(18, 26, 43, 0.75);
        border-radius: 14px;
        padding: 0.25rem 0.25rem;
    }
    div[data-testid="stChatMessage"] a { color: var(--sleeper-accent) !important; }
    div[data-testid="stChatMessage"] code {
        background: var(--sleeper-text);
        border: 1px solid var(--sleeper-border);
        color: var(sleeper-bg);
        border-radius: 8px;
        padding: 0.1rem 0.3rem;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'username' not in st.session_state:
    st.session_state.username = None
if 'league_id' not in st.session_state:
    st.session_state.league_id = None
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'thread_id' not in st.session_state:
    st.session_state.thread_id = "1"
if 'use_langgraph_server' not in st.session_state:
    st.session_state.use_langgraph_server = bool(LANGGRAPH_SERVER_URL)

# Header with logo
logo_path = project_root / "assets" / "sleeper.jpg"
if logo_path.exists():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image(str(logo_path), width=200)
        st.markdown("<h1 class='main-header'>My Sleeper Buddy</h1>", unsafe_allow_html=True)
else:
    st.markdown("<h1 class='main-header'>My Sleeper Buddy</h1>", unsafe_allow_html=True)

# Main app logic
if not st.session_state.data_loaded:
    # Input form
    st.markdown("### Enter Your Sleeper Information")
    
    with st.form("user_input_form"):
        username = st.text_input("Username", placeholder="Enter your Sleeper username")
        league_id = st.text_input("League ID", placeholder="Enter your Sleeper League ID")
        submit_button = st.form_submit_button("Load Data", type="primary")
        
        if submit_button:
            if not league_id:
                st.error("Please enter a League ID")
            else:
                # Store the values
                st.session_state.username = username if username else None
                st.session_state.league_id = league_id
                
                # Show loading screen
                with st.spinner("Loading your Sleeper data... This may take a few moments."):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    try:
                        # Update progress
                        status_text.text("Fetching league information...")
                        progress_bar.progress(10)
                        
                        # Run data extraction
                        extract_data(username=st.session_state.username, league_id=st.session_state.league_id)
                        
                        progress_bar.progress(100)
                        status_text.text("Data loaded successfully!")
                        
                        # Small delay to show completion
                        time.sleep(1)

                        # Initialize thread for deployed LangGraph server mode
                        if st.session_state.use_langgraph_server:
                            user_id = st.session_state.username or "anonymous"
                            thread = _lg_create_thread(user_id=user_id)
                            st.session_state.thread_id = thread["thread_id"]
                        
                        # Mark data as loaded
                        st.session_state.data_loaded = True
                        
                        # Add welcome message
                        welcome_msg = f"Welcome! Your Sleeper data has been loaded. How can I help you today?"
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": welcome_msg
                        })
                        
                        # Rerun to show chat interface
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Error loading data: {str(e)}")
                        st.exception(e)
                        progress_bar.empty()
                        status_text.empty()

else:
    # Chat interface
    st.markdown("### Chat with Buddy")
    
    # Display chat history using Streamlit's chat components
    for message in st.session_state.messages:
        if message["role"] == "user":
            with st.chat_message("user"):
                st.write(message["content"])
        else:
            with st.chat_message("assistant"):
                st.write(message["content"])
    
    # Chat input
    user_input = st.chat_input("Ask Buddy about your fantasy league...")
    
    if user_input:
        # Add user message to history
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })

        full_response_parts: list[str] = []
        try:
            def response_generator():
                if not st.session_state.use_langgraph_server:
                    raise RuntimeError(
                        "LANGGRAPH_SERVER_URL is not set, so deployed thread-based chat is unavailable. "
                        "Set LANGGRAPH_SERVER_URL (Render LangGraph API URL) and restart."
                    )
                for chunk in _lg_stream(
                    st.session_state.thread_id,
                    user_input,
                    username=st.session_state.username,
                    league_id=st.session_state.league_id,
                ):
                    full_response_parts.append(chunk)
                    yield chunk

            with st.chat_message("assistant"):
                st.write_stream(response_generator())

            st.session_state.messages.append({
                "role": "assistant",
                "content": "".join(full_response_parts)
            })

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            with st.chat_message("assistant"):
                st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
        
        # Rerun to show the complete conversation
        st.rerun()
    
    # Sidebar with reset option
    with st.sidebar:
        st.markdown("### Options")
        if st.button("Reset Session", type="secondary"):
            st.session_state.data_loaded = False
            st.session_state.username = None
            st.session_state.league_id = None
            st.session_state.messages = []
            st.session_state.thread_id = "1"
            st.rerun()
        
        st.markdown("---")
        st.markdown(f"**Username:** {st.session_state.username or 'Not provided'}")
        st.markdown(f"**League ID:** {st.session_state.league_id}")
