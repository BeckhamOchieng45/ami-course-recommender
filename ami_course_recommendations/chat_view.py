"""
Streaming chat endpoint for the AMI AI Coach.

POST /api/chat

Accepts a question about a specific course recommendation, builds a
full-context system prompt from the user's profile and recommendation
data, and streams the response back as Server-Sent Events (SSE).

SSE format (each line):
    data: <text chunk>\\n\\n
    data: [DONE]\\n\\n   <- signals end of stream

Why SSE over WebSocket:
- One-directional (server → client) is all we need for streaming LLM output
- Works over plain HTTP, no upgrade handshake
- Native browser EventSource API handles reconnect automatically
- No additional library required on either side

Why not a standard JsonResponse:
- Streaming starts before the full response is generated
- Groq's streaming API yields tokens as they arrive (~50ms each)
- The UI can start rendering immediately rather than waiting 3-5s
"""

import json
import logging

from django.http import StreamingHttpResponse, JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from ami_course_recommendations.models import User
from ami_course_recommendations.auth_views import jwt_required
from engine import llm

logger = logging.getLogger(__name__)

# Maximum number of turns to keep in conversation history.
# Keeps the context window bounded and costs low.
MAX_HISTORY_TURNS: int = 10


def _sse_chunk(text: str) -> str:
    """Format a text chunk as an SSE data line."""
    # Escape newlines inside the chunk so each data: line is single-line
    escaped = text.replace("\n", "\\n")
    return f"data: {escaped}\n\n"


def _sse_done() -> str:
    """Terminal SSE event signalling the stream is complete."""
    return "data: [DONE]\n\n"


def _sse_error(message: str) -> str:
    """SSE error event — client checks for this prefix."""
    return f"data: [ERROR] {message}\n\n"


@method_decorator(csrf_exempt, name="dispatch")
class ChatView(View):
    """
    POST /api/chat

    Request body (JSON):
        {
            "user_id":    "USR-00042",
            "course_id":  "CRS-ENT-001",
            "question":   "Why is this course right for me specifically?",
            "recommendation": { ...full rec object from /recommendations... },
            "history": [
                {"role": "user",      "content": "previous question"},
                {"role": "assistant", "content": "previous answer"}
            ]
        }

    Response: text/event-stream SSE
        data: Hello\\n\\n
        data:  there\\n\\n
        data: [DONE]\\n\\n
    """

    @jwt_required
    def post(self, request):
        # ── Parse request body ────────────────────────────────────────────
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        user_id      = body.get("user_id", "").strip()
        question     = body.get("question", "").strip()
        recommendation = body.get("recommendation", {})
        history      = body.get("history", [])

        if not user_id:
            return JsonResponse({"error": "user_id is required"}, status=400)
        if not question:
            return JsonResponse({"error": "question is required"}, status=400)
        if len(question) > 500:
            return JsonResponse(
                {"error": "question too long (max 500 characters)"}, status=400
            )

        # ── Fetch user profile ────────────────────────────────────────────
        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found"}, status=404)

        user_profile = {
            "role":             user.role,
            "industry":         user.industry,
            "seniority":        user.seniority,
            "stated_goal":      user.stated_goal,
            "usage_confidence": recommendation.get("usage_confidence", 0),
        }

        # ── Build system message ──────────────────────────────────────────
        course = recommendation.get("course", {})
        system_message = llm.build_chat_system_message(
            user_profile=user_profile,
            course=course,
            recommendation=recommendation,
        )

        # ── Sanitise and cap conversation history ─────────────────────────
        # Only keep role + content, cap to MAX_HISTORY_TURNS pairs
        clean_history = [
            {"role": m["role"], "content": m["content"]}
            for m in history
            if m.get("role") in ("user", "assistant") and m.get("content")
        ][-MAX_HISTORY_TURNS * 2:]  # 2 messages per turn

        # Append the new question
        messages = clean_history + [{"role": "user", "content": question}]

        # ── Stream ────────────────────────────────────────────────────────
        def event_stream():
            try:
                for chunk in llm.stream_chat(system_message, messages):
                    yield _sse_chunk(chunk)
                yield _sse_done()
            except Exception as exc:
                logger.error("Chat stream error: %s", exc)
                yield _sse_error(str(exc))

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        # SSE headers — prevent buffering at every layer
        response["Cache-Control"]     = "no-cache"
        response["X-Accel-Buffering"] = "no"   # Nginx passthrough
        response["Access-Control-Allow-Origin"] = "*"
        return response

    def options(self, request):
        """Handle CORS preflight."""
        response = JsonResponse({})
        response["Access-Control-Allow-Origin"]  = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response
