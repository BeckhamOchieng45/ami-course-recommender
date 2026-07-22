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


# ---------------------------------------------------------------------------
# Chat system prompt — full coaching context
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_PROMPT = """You are the AMI AI Coach — a warm, direct, outcomes-focused learning advisor
for African entrepreneurs, SME managers, and corporate employees.

A learner is asking you follow-up questions about a specific course recommendation they received.
You have been given full context about:
- The learner's profile (role, industry, seniority, stated goal)
- The recommended course (title, level, skills taught)
- Exactly why the engine recommended it (which signals fired and how much they contributed)

Your job:
1. Explain the recommendation in plain language the learner will find useful and motivating.
2. Answer their question directly and honestly — if a course might not be right for them, say so.
3. Connect the recommendation to their stated goal and work context wherever possible.
4. Be warm but concise. Do not pad answers. Do not repeat information they didn't ask about.
5. Never mention scores, weights, percentages, algorithms, or "the engine". 
   Speak as a coach who knows the learner, not as a system explaining itself.
6. If they ask something outside course recommendations, gently redirect to their learning path.

Context about this learner and recommendation is provided below.
"""


def build_chat_system_message(
    user_profile: dict,
    course: dict,
    recommendation: dict,
) -> str:
    """
    Build the full system message for the coaching chat, embedding the
    learner's profile and recommendation context so Groq can answer
    follow-up questions with specific, grounded answers.

    Args:
        user_profile:   Dict with role, industry, seniority, stated_goal, usage_confidence
        course:         Dict with title, level, programme_area, skills_taught, duration_mins
        recommendation: Dict with reason, reason_detail, reason_driver, score_breakdown
    """
    conf = user_profile.get("usage_confidence", 0)
    signal_mode = (
        "no usage history yet (cold-start — recommendations based on survey and work context only)"
        if conf == 0
        else f"{int(conf * 100)}% behavior-driven (based on actual course completions)"
        if conf < 1
        else "fully behavior-driven (rich completion history available)"
    )

    # Summarise which signal contributed most
    breakdown = recommendation.get("score_breakdown", [])
    if breakdown:
        top = max(breakdown, key=lambda b: b.get("contribution", 0))
        top_signal = top.get("component", "").replace("_", " ")
        signal_summary = f"The primary signal was '{top_signal}'."
    else:
        signal_summary = ""

    skills = ", ".join(course.get("skills_taught", []))

    return f"""{_CHAT_SYSTEM_PROMPT}

--- LEARNER PROFILE ---
Role: {user_profile.get('role', 'unknown').replace('_', ' ')}
Industry: {user_profile.get('industry', 'unknown').replace('_', ' ')}
Seniority: {user_profile.get('seniority', 'unknown').replace('-', ' ')}
Stated goal: {user_profile.get('stated_goal', 'not provided')}
Signal mode: {signal_mode}

--- RECOMMENDED COURSE ---
Title: {course.get('title', '')}
Level: {course.get('level', '')}
Programme area: {course.get('programme_area', '').replace('_', ' ')}
Duration: {course.get('duration_mins', '')} minutes
Skills taught: {skills}

--- WHY THIS WAS RECOMMENDED ---
Reason: {recommendation.get('reason', '')}
Detail: {recommendation.get('reason_detail', '')}
Primary driver: {recommendation.get('reason_driver', '')}
{signal_summary}
"""


def stream_chat(
    system_message: str,
    messages: list[dict],
) -> "Iterator[str]":
    """
    Stream a coaching chat response token-by-token using Groq.

    Yields raw text chunks as they arrive. The caller is responsible for
    assembling them into an SSE stream or WebSocket messages.

    If Groq is unavailable, yields a single fallback message so the UI
    always gets a response.

    Args:
        system_message: Full context-rich system prompt from build_chat_system_message()
        messages:       Conversation history as [{"role": "user"|"assistant", "content": "..."}]

    Yields:
        str: text chunks from the LLM stream
    """
    from typing import Iterator

    client = _get_client()
    if client is None:
        yield (
            "The AI coach is not available right now — GROQ_API_KEY is not configured. "
            "Set it in your .env file to enable live coaching conversations."
        )
        return

    try:
        stream = client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": system_message},
                *messages,
            ],
            temperature=0.5,
            max_tokens=600,       # Generous for a chat response, but capped
            stream=True,
            timeout=30.0,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    except Exception as exc:
        logger.warning("Groq chat stream failed: %s", exc)
        yield f"Sorry, I ran into an issue generating a response. Please try again. (Error: {exc})"
