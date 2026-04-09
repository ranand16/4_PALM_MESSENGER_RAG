"""
rag_engine.py
-------------
Uses Google Generative AI (Gemini / PaLM) to generate a concise, human-friendly
digest from the notifications currently stored in ChromaDB.

The pipeline follows a map-reduce RAG pattern:
  1. Map   – summarise each batch of notifications individually.
  2. Reduce – combine all batch summaries into one final digest.
"""

# [PYTHON] This future import postpones evaluation of type hints until runtime access, which helps avoid some circular-reference issues.
from __future__ import annotations

# [PYTHON] `os` gives access to environment variables and operating-system helpers.
import os
# [PYTHON] `textwrap` provides utilities for cleaning indentation in multiline strings.
import textwrap
# [PYTHON] `List` is a type hint that documents we expect a list of a specific type.
from typing import List

# [FUNCTIONALITY] Import the Google Generative AI SDK and alias it as `genai` so calls are shorter.
import google.generativeai as genai

# [FUNCTIONALITY] Import data-access function that fetches recent notifications from storage.
from notification_store import get_recent_notifications

# [FUNCTIONALITY] Limit how many notification lines are sent in one LLM request to keep prompt size stable and cheaper.
BATCH_SIZE = 20

# [PYTHON] `textwrap.dedent` removes common leading spaces from triple-quoted text so prompt formatting is predictable.
# [FUNCTIONALITY] Prompt template used in the map step: summarize one batch independently.
_MAP_PROMPT = textwrap.dedent("""\
    You are a helpful assistant summarising smartphone notifications.
    Below is a batch of notifications. Extract the key information concisely.

    Notifications:
    {notifications}

    Concise summary:""")

# [FUNCTIONALITY] Prompt template used in the reduce step: merge multiple batch summaries into one final digest.
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
    # [PYTHON] Function signature: `prompt: str` means caller should pass a string; `-> str` means function returns a string.
    """Call the Gemini model and return the response text."""
    # [FUNCTIONALITY] Read API key from environment; empty string fallback prevents immediate KeyError but may fail at request time.
    api_key = os.getenv("GOOGLE_API_KEY", "")
    # [FUNCTIONALITY] Configure SDK once per call with the API key so requests are authenticated.
    genai.configure(api_key=api_key)
    # [FUNCTIONALITY] Instantiate Gemini model client; this object is used to send prompts.
    model = genai.GenerativeModel("gemini-pro")
    # [FUNCTIONALITY] Send prompt text to model and receive a structured response object.
    response = model.generate_content(prompt)
    # [PYTHON] `.strip()` removes leading/trailing whitespace/newlines, giving cleaner plain-text output.
    return response.text.strip()


def build_digest() -> str:
    # [PYTHON] Public function returning a single digest string for e-mail delivery.
    """
    Retrieve all stored notifications, run them through the RAG pipeline, and
    return a formatted digest string ready to be e-mailed.
    """
    # [FUNCTIONALITY] Fetch notifications from the storage layer (each item is expected to include a `document` field).
    notifications = get_recent_notifications()

    # [PYTHON] Empty lists are falsy in Python, so `if not notifications` checks for no data.
    if not notifications:
        # [FUNCTIONALITY] Return a friendly no-op message so downstream e-mail still has meaningful content.
        return "No new notifications since the last digest."

    # [PYTHON] List comprehension: iterate each notification dict `n` and extract `n["document"]` into a new list.
    # [FUNCTIONALITY] Keep only raw text content for LLM summarization; metadata is ignored in this pipeline.
    documents: List[str] = [n["document"] for n in notifications]

    # [FUNCTIONALITY] Map step: summarize each chunk separately to reduce token pressure and preserve coverage.
    batch_summaries: List[str] = []
    # [PYTHON] `range(start, stop, step)` with `step=BATCH_SIZE` iterates start indices: 0, 20, 40, ...
    for i in range(0, len(documents), BATCH_SIZE):
        # [PYTHON] Slicing `documents[i : i + BATCH_SIZE]` safely returns up to batch size without IndexError.
        batch = documents[i : i + BATCH_SIZE]
        # [FUNCTIONALITY] Join batch lines with newline separators and inject into map prompt template.
        prompt = _MAP_PROMPT.format(notifications="\n".join(batch))
        # [FUNCTIONALITY] Call LLM for this batch and store resulting mini-summary.
        batch_summaries.append(_llm(prompt))

    # [FUNCTIONALITY] Optimization: if only one batch exists, no reduce step is needed.
    if len(batch_summaries) == 1:
        return batch_summaries[0]

    # [FUNCTIONALITY] Reduce step: combine all map summaries into a single coherent digest.
    # [PYTHON] `"\n\n".join(...)` places blank lines between summaries for readability/context separation.
    prompt = _REDUCE_PROMPT.format(summaries="\n\n".join(batch_summaries))
    # [FUNCTIONALITY] Final LLM call returns user-facing digest text used by e-mail sender.
    return _llm(prompt)
