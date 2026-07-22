"""
API views for course recommendations.

Endpoint:
    GET /users/{user_id}/recommendations?n=5

Returns top-N ranked recommendations for a user with per-component score
breakdown. Payload is intentionally lean — nod to AMI's mobile-first,
sometimes low-bandwidth learner base.

Data fetching lives here; scoring logic lives in engine/. This boundary
keeps each scorer unit-testable without DB access and makes the
'add a new signal' extension point clean.
"""

from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from ami_course_recommendations.models import User, Course
from engine.filters import get_candidates
from engine.coldstart import rank_courses
from engine.explainer import build_recommendations
from engine import llm as groq_llm

# Maximum recommendations a caller can request in one response
MAX_N: int = 20

# Default number of recommendations when ?n= is absent
DEFAULT_N: int = 5


def _serialize_recommendation(rec) -> dict:
    """
    Serialize a Recommendation object to a lean JSON-compatible dict.

    coaching_reason: Groq-enhanced version in AMI's coaching voice.
                     Identical to reason when GROQ_API_KEY is not set.
    """
    return {
        "position": rec.position,
        "course": {
            "course_id": rec.course.course_id,
            "title": rec.course.title,
            "programme_area": rec.course.programme_area,
            "level": rec.course.level,
            "duration_mins": rec.course.duration_mins,
            "is_paid": rec.course.is_paid,
            "skills_taught": rec.course.skills_taught,
        },
        "score": rec.score,
        "usage_confidence": rec.usage_confidence,
        "reason": rec.reason,
        "coaching_reason": rec.coaching_reason,
        "reason_detail": rec.reason_detail,
        "reason_driver": rec.reason_driver,
        "score_breakdown": rec.score_breakdown,
    }


@method_decorator(csrf_exempt, name="dispatch")
class RecommendationsView(View):
    """
    GET /users/{user_id}/recommendations?n=5

    Query params:
        n (int, optional): Number of recommendations to return. Default 5, max 20.

    Response (200):
        {
            "user_id": "USR-00042",
            "usage_confidence": 0.6,
            "recommendation_count": 5,
            "recommendations": [ ... ]
        }

    Response (404):
        { "error": "User not found", "user_id": "..." }

    Response (400):
        { "error": "Invalid value for n: ...", "detail": "..." }
    """

    def get(self, request, user_id: str):
        # --- Parse and validate ?n ---
        n_param = request.GET.get("n", str(DEFAULT_N))
        try:
            n = int(n_param)
            if n < 1 or n > MAX_N:
                return JsonResponse(
                    {
                        "error": f"Invalid value for n: {n_param}",
                        "detail": f"n must be between 1 and {MAX_N}",
                    },
                    status=400,
                )
        except ValueError:
            return JsonResponse(
                {
                    "error": f"Invalid value for n: {n_param}",
                    "detail": "n must be an integer",
                },
                status=400,
            )

        # --- Fetch user ---
        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return JsonResponse(
                {"error": "User not found", "user_id": user_id},
                status=404,
            )

        # --- Get candidate courses (hard filters applied) ---
        all_courses = list(Course.objects.all())
        candidates = get_candidates(user, all_courses)

        if not candidates:
            return JsonResponse(
                {
                    "user_id": user_id,
                    "usage_confidence": 0.0,
                    "llm_enhanced": groq_llm.is_available(),
                    "recommendation_count": 0,
                    "recommendations": [],
                    "message": "No eligible courses found. You may have completed all available courses.",
                },
                status=200,
            )

        # --- Score, rank, explain ---
        ranked = rank_courses(user, candidates)
        recommendations = build_recommendations(user, ranked, n=n)

        # --- Serialize ---
        usage_confidence = ranked[0].usage_confidence if ranked else 0.0

        return JsonResponse(
            {
                "user_id": user_id,
                "usage_confidence": usage_confidence,
                "llm_enhanced": groq_llm.is_available(),
                "recommendation_count": len(recommendations),
                "recommendations": [
                    _serialize_recommendation(r) for r in recommendations
                ],
            },
            status=200,
        )
