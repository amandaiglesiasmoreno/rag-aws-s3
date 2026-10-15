"""Streamlit front end: conversational RAG (OpenAI + Amazon S3 Vectors), chat history in S3."""
import logging
import uuid

import streamlit as st

import chat_store
import rag_core
from config import APP_PASSWORD, HISTORY_TURNS, LLM_MODEL

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
st.set_page_config(page_title="RAG Assistant", page_icon="📚", layout="centered")


# ---------- Password gate (app is reachable on a public IP) ----------
def check_password() -> bool:
    if not APP_PASSWORD or st.session_state.get("authenticated"):
        return True
    st.title("📚 RAG Assistant")
    pwd = st.text_input("Password", type="password")
    if st.button("Log in"):
        if pwd == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        st.error("Wrong password")
    return False


if not check_password():
    st.stop()


# ---------- Session: id lives in the URL (?session=...) so a refresh resumes the chat ----------
def start_new_session():
    sid = uuid.uuid4().hex
    st.query_params["session"] = sid
    st.session_state.session_id = sid
    st.session_state.messages = []


if "session_id" not in st.session_state:
    sid = st.query_params.get("session", "")
    if chat_store.is_valid_session_id(sid):
        st.session_state.session_id = sid
        st.session_state.messages = chat_store.load_history(sid)  # resume from S3
    else:
        start_new_session()

session_id = st.session_state.session_id


def llm_history() -> list[dict]:
    """Last N messages, only role/content (what OpenAI expects)."""
    msgs = st.session_state.messages[-HISTORY_TURNS:]
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def show_sources(sources: list[dict]):
    if not sources:
        return
    with st.expander(f"Sources ({len(sources)})"):
        for s in sources:
            st.markdown(f"**{s['source']}** · chunk {s['chunk_index']} · distance {s['distance']:.3f}")
            st.caption(s["content"][:500] + ("..." if len(s["content"]) > 500 else ""))


@st.cache_data(ttl=300)
def cached_kb_stats():
    # Listing vectors costs API calls -> cache for 5 minutes
    return rag_core.count_chunks_by_source()


# ---------- Sidebar ----------
with st.sidebar:
    st.header("⚙️ Session")
    st.caption(f"Session ID: `{session_id}`")
    st.caption("Bookmark this page URL to continue the conversation later (kept 7 days).")
    if st.button("➕ New conversation"):
        start_new_session()
        st.rerun()
    if st.button("🗑️ Delete this conversation"):
        chat_store.delete_history(session_id)
        start_new_session()
        st.rerun()
    show_debug = st.toggle("Show RAG debug info", value=False)

    st.divider()
    st.header("📄 Knowledge base")
    try:
        sources = cached_kb_stats()
        if sources:
            for src, n in sources:
                st.write(f"• {src} ({n} chunks)")
        else:
            st.caption("No documents indexed. Upload files to S3 docs/ and run the indexer.")
    except Exception as e:
        st.error(f"Vector index not reachable: {e}")
    st.caption(f"Model: `{LLM_MODEL}`")

# ---------- Chat ----------
st.title("📚 RAG Assistant")
st.caption("Ask me anything about the knowledge base.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            show_sources(msg.get("sources", []))

if query := st.chat_input("Type your question..."):
    history = llm_history()  # history BEFORE the new message (same as the Telegram bot)
    user_msg = {"role": "user", "content": query, "timestamp": chat_store.now_iso()}
    st.session_state.messages.append(user_msg)
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching the knowledge base..."):
                standalone_query = rag_core.reformulate_query(history, query)
                chunks = rag_core.retrieve_context(standalone_query)

            if show_debug:
                st.info(f"**Reformulated query:** {standalone_query}")

            if chunks:
                answer = st.write_stream(rag_core.stream_answer(history, query, chunks))
            else:
                answer = rag_core.NO_CONTEXT_ANSWER
                st.markdown(answer)
            show_sources(chunks)
        except Exception as e:
            logging.exception("RAG pipeline failed")
            answer, chunks, standalone_query = f"Sorry, something went wrong: {e}", [], query
            st.error(answer)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "timestamp": chat_store.now_iso(),
            "reformulated_query": standalone_query,
            "sources": chunks,
        }
    )
    # Persist the whole conversation to S3 (one small JSON per session)
    try:
        chat_store.save_history(session_id, st.session_state.messages)
    except Exception as e:
        st.warning(f"Could not save chat history to S3: {e}")
