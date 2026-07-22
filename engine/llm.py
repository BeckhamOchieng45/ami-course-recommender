"""
Groq LLM client for coaching-tone reason enhancement.

Design contract:
- The core ranking/scoring logic never touches this module.
- This module's ONLY job is to take a templated reason string (produced by
  explainer.py) and re-voice it in AMI's coaching tone.
- If GROQ_API_KEY is absent, empty, or the API call fails for any reason,
  the function returns the original templated reason unchanged.
- The API endpoint always has a valid `reason` field regardless of whether
  Groq is configured — the LLM is an enhancement, never a requirement.

Why Groq specifically:
- Fastest inference latency of current hosted LLM APIs (llama-3.3-70b via
  Groq typically < 300ms), which matters for a per-request enhancement
- OpenAI-compatible client interface — easy to swap to another provider
- No token cost concern for short reason strings (< 200 tokens per call)

Model: openai/gpt-oss-120b via Groq
- Highest quality instruction-following available on Groq
- Fast inference, well-suited for short tone-rewriting tasks
- Can be overridden via GROQ_MODEL env var
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — AMI coaching voice
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are the AMI AI Coach — a warm, direct, outcome-focused
learning advisor for African entrepreneurs, SME managers, and corporate employees.

Your job is to rewrite a course recommendation reason in AMI's coaching voice.

Rules:
1. Keep the core factual claim EXACTLY intact — do not change which course is
   recommended or why (the underlying signal is audited).
2. Make it warmer, more personal, and action-oriented — like advice from a trusted
   coach, not a recommendation algorithm.
3. Write in second person ("you", "your").
4. One to two sentences maximum. Be concise.
5. Do NOT add qualifiers like "I think" or "perhaps". Be direct.
6. Do NOT mention scores, weights, algorithms, or data signals.
7. Return ONLY the rewritten reason. No preamble, no explanation."""


# ---------------------------------------------------------------------------
# Lazy client initialisation
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    """
    Return a configured Groq client, or None if the API key is not set.
    Initialised lazily so the import doesn't fail when the key is absent.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from groq import Groq
        _client = Groq(api_key=api_key)
        logger.info("Groq client initialised (model: %s)", _get_model())
        return _client
    except Exception as exc:
        logger.warning("Failed to initialise Groq client: %s", exc)
        return None


def _get_model() -> str:
    return os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")


def is_available() -> bool:
    """Return True if a Groq API key is configured and the client loaded."""
    return _get_client() is not None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enhance_reason(
    templated_reason: str,
    context: Optional[str] = None,
) -> str:
    """
    Re-voice a templated recommendation reason in AMI's coaching tone using Groq.

    Args:
        templated_reason: The deterministic reason string from build_reason().
        context:          Optional extra context for the prompt (e.g. user's
                          stated goal), used to make the tone more personal.

    Returns:
        Enhanced reason string if Groq is available and the call succeeds.
        Falls back to the original templated_reason on any failure.
    """
    client = _get_client()
    if client is None:
        # No key configured — silent passthrough, no error
        return templated_reason

    user_message = templated_reason
    if context:
        user_message = f"Learner context: {context}\n\nReason to rewrite: {templated_reason}"

    try:
        response = client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.4,      # Low enough to stay factual, enough for warmth
            max_tokens=120,        # Reason strings are short; cap tokens hard
            timeout=5.0,           # Never block the API response > 5 seconds
        )
        enhanced = response.choices[0].message.content.strip()

        # Safety check: if the LLM returned something suspiciously short or
        # empty, fall back to the original
        if len(enhanced) < 20:
            logger.warning("Groq returned suspiciously short response, using template")
            return templated_reason

        return enhanced

    except Exception as exc:
        # Log but never raise — the recommendation must always return
        logger.warning("Groq enhancement failed (%s), using templated reason", exc)
        return templated_reason
