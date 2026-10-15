"""RAG logic (from the Telegram bot): reformulation, retrieval (S3 Vectors) and generation (OpenAI)."""
import logging

from openai import OpenAI

import vector_store
from config import EMBEDDING_MODEL, LLM_MODEL, MAX_DISTANCE, OPENAI_API_KEY, TOP_K

logger = logging.getLogger(__name__)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

NO_CONTEXT_ANSWER = "I don't have enough information in my knowledge base to answer that."


def get_embedding(text: str) -> list[float]:
    response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def retrieve_context(query: str, k: int = TOP_K) -> list[dict]:
    results = vector_store.query(get_embedding(query), k)
    logger.info("=== RAG DEBUG: Query -> '%s' ===", query)
    for r in results:
        logger.info("%s#%s | distance %.4f | %s...", r["source"], r["chunk_index"], r["distance"], r["content"][:100])
    return [r for r in results if r["distance"] <= MAX_DISTANCE]  # drop clearly irrelevant chunks


REFORMULATION_PROMPT = (
    "You are an expert query reformulation assistant for a RAG system. "
    "Your task is to analyze the chat history and rewrite the user's latest message "
    "into a complete, standalone query that requires no prior context to be understood.\n\n"
    "Apply these core strategies where necessary:\n"
    "1. Resolve Pronouns: Replace ambiguous pronouns (e.g., it, he, them, that) with the specific entities mentioned previously.\n"
    "2. Clarify Implicit Comparisons: If the user asks about a new element in relation to a previously discussed one, explicitly name both elements to form a comparative query.\n"
    "3. Complete Elliptical Queries: Fill in missing subjects, verbs, or context that the user omitted assuming you would remember.\n\n"
    "STRICT CONSTRAINTS:\n"
    "- If the latest message is a greeting, conversational filler, or already fully self-contained, return it EXACTLY as is.\n"
    "- DO NOT attempt to answer the question.\n"
    "- OUTPUT ONLY the reformulated query text. Do not include quotes, prefixes like 'Rewritten query:', or explanations."
)


def reformulate_query(history: list[dict], current_query: str) -> str:
    if not history:
        return current_query
    messages = [{"role": "system", "content": REFORMULATION_PROMPT}, *history]
    messages.append({"role": "user", "content": f"Latest message: {current_query}"})
    response = openai_client.chat.completions.create(model=LLM_MODEL, messages=messages)
    return response.choices[0].message.content.strip()


def build_answer_messages(history: list[dict], original_query: str, chunks: list[dict]) -> list[dict]:
    context = "\n\n---\n\n".join(f"[Source: {c['source']}]\n{c['content']}" for c in chunks)
    system = (
        "Answer the user's question using ONLY the provided context. "
        "If the context does not contain the answer, say so. "
        "Mention the source file names you used at the end of the answer.\n\n"
        f"Context:\n{context}"
    )
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": original_query}]


def stream_answer(history: list[dict], original_query: str, chunks: list[dict]):
    """Yields the answer token by token (for st.write_stream)."""
    stream = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=build_answer_messages(history, original_query, chunks),
        stream=True,
    )
    for event in stream:
        if event.choices and event.choices[0].delta.content:
            yield event.choices[0].delta.content


def count_chunks_by_source() -> list[tuple[str, int]]:
    return vector_store.count_chunks_by_source()
