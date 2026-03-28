"""
rag_engine.py
-------------
Uses Google Generative AI (Gemini / PaLM) to generate a concise, human-friendly
digest from the notifications currently stored in ChromaDB.

The pipeline follows a map-reduce RAG pattern:
  1. Map   – summarise each batch of notifications individually.
  2. Reduce – combine all batch summaries into one final digest.
"""

from __future__ import annotations

import os
import textwrap
from typing import List

import google.generativeai as genai

from notification_store import get_recent_notifications

# Maximum number of notification lines per LLM call (keeps prompts manageable)
BATCH_SIZE = 20

_MAP_PROMPT = textwrap.dedent("""\
    You are a helpful assistant summarising smartphone notifications.
    Below is a batch of notifications. Extract the key information concisely.

    Notifications:
    {notifications}

    Concise summary:""")

_REDUCE_PROMPT = textwrap.dedent("""\
    You are a helpful assistant producing a consolidated notification digest.
    Below are summaries from notification batches received while the user was
    away from their phone.
    Produce a single, well-structured digest grouped by app
    (e.g. WhatsApp, Telegram, Signal). Highlight anything that sounds urgent.

    Summaries:
    {summaries}

    Final digest:""")


def _llm(prompt: str) -> str:
    """Call the Gemini model and return the response text."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-pro")
    response = model.generate_content(prompt)
    return response.text.strip()


def build_digest() -> str:
    """
    Retrieve all stored notifications, run them through the RAG pipeline, and
    return a formatted digest string ready to be e-mailed.
    """
    notifications = get_recent_notifications()

    if not notifications:
        return "No new notifications since the last digest."

    documents: List[str] = [n["document"] for n in notifications]

    # ── Map step ─────────────────────────────────────────────────────────────
    batch_summaries: List[str] = []
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        prompt = _MAP_PROMPT.format(notifications="\n".join(batch))
        batch_summaries.append(_llm(prompt))

    if len(batch_summaries) == 1:
        return batch_summaries[0]

    # ── Reduce step ──────────────────────────────────────────────────────────
    prompt = _REDUCE_PROMPT.format(summaries="\n\n".join(batch_summaries))
    return _llm(prompt)
