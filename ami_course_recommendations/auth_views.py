"""
Authentication and learner-list API views.

Endpoints:
    POST /api/auth/login    — email + password → access + refresh tokens
    POST /api/auth/refresh  — refresh token → new access token
    GET  /api/auth/me       — current user profile (requires Bearer token)
    GET  /api/learners      — paginated learner list with profile stats

JWT approach:
    Uses simplejwt under the hood. The existing plain Django views
    (RecommendationsView, ChatView) are not DRF APIViews, so they bypass
    DRF's DEFAULT_AUTHENTICATION_CLASSES. A shared `jwt_required` decorator
    is used to enforce auth on those views without rewriting them.
"""

import json
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate
from django.contrib.auth.models import User as DjangoUser
from django.db.models import Count, Q

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.authentication import JWTAuthentication

from ami_course_recommendations.models import User as LearnerUser, UsageEvent


# ---------------------------------------------------------------------------
# JWT helper — used by existing plain-View endpoints
# ---------------------------------------------------------------------------

def _get_token_user(request) -> DjangoUser | None:
    """
    Extract and validate the Bearer token from the Authorization header.
    Returns the Django user if valid, None otherwise.
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    try:
        jwt_auth = JWTAuthentication()
        validated = jwt_auth.get_validated_token(
            jwt_auth.get_raw_token(
                jwt_auth.get_header(request)
            )
        )
        return jwt_auth.get_user(validated)
    except Exception:
        return None


def jwt_required(view_func):
    """
    Decorator that enforces JWT authentication on plain Django views.
    Returns 401 if the token is missing or invalid.
    """
    def wrapper(self, request, *args, **kwargs):
        user = _get_token_user(request)
        if user is None:
            return JsonResponse(
                {"error": "Authentication required", "detail": "Provide a valid Bearer token."},
                status=401,
            )
        request.jwt_user = user
        return view_func(self, request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class LoginView(View):
    """
    POST /api/auth/login

    Body: { "email": "...", "password": "..." }

    Returns:
        { "access": "...", "refresh": "...", "user": { id, email, name, is_staff } }

    Uses Django's built-in auth — email is matched against username field
    (superuser is created with email as both email and username).
    """

    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        email    = body.get("email", "").strip().lower()
        password = body.get("password", "")

        if not email or not password:
            return JsonResponse(
                {"error": "email and password are required"},
                status=400,
            )

        # Try authenticating with username = email (our convention)
        user = authenticate(request, username=email, password=password)

        # Also try matching by email field in case username differs
        if user is None:
            try:
                django_user = DjangoUser.objects.get(email__iexact=email)
                user = authenticate(request, username=django_user.username, password=password)
            except (DjangoUser.DoesNotExist, DjangoUser.MultipleObjectsReturned):
                pass

        if user is None or not user.is_active:
            return JsonResponse(
                {"error": "Invalid credentials"},
                status=401,
            )

        refresh = RefreshToken.for_user(user)

        return JsonResponse({
            "access":  str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id":       user.id,
                "email":    user.email,
                "name":     user.get_full_name() or user.username,
                "is_staff": user.is_staff,
            },
        })


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class TokenRefreshView(View):
    """
    POST /api/auth/refresh

    Body: { "refresh": "..." }

    Returns: { "access": "..." }
    """

    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        refresh_token = body.get("refresh", "")
        if not refresh_token:
            return JsonResponse({"error": "refresh token is required"}, status=400)

        try:
            token = RefreshToken(refresh_token)
            return JsonResponse({"access": str(token.access_token)})
        except (TokenError, InvalidToken) as e:
            return JsonResponse({"error": "Invalid or expired refresh token", "detail": str(e)}, status=401)


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class MeView(View):
    """
    GET /api/auth/me

    Returns the authenticated user's profile.
    Requires: Authorization: Bearer <access_token>
    """

    @jwt_required
    def get(self, request):
        user = request.jwt_user
        return JsonResponse({
            "id":       user.id,
            "email":    user.email,
            "name":     user.get_full_name() or user.username,
            "is_staff": user.is_staff,
        })


# ---------------------------------------------------------------------------
# GET /api/learners
# ---------------------------------------------------------------------------

_ROLE_LABELS = {
    "micro_business_owner": "Micro-Business Owner",
    "sme_manager":          "SME Manager",
    "corporate_employee":   "Corporate Employee",
    "senior_executive":     "Senior Executive",
}

_SENIORITY_LABELS = {
    "micro-entrepreneur": "Micro-Entrepreneur",
    "sme-manager":        "SME Manager",
    "early-career":       "Early Career",
    "senior-leader":      "Senior Leader",
}

_INDUSTRY_LABELS = {
    "retail":               "Retail",
    "agriculture":          "Agriculture",
    "financial_services":   "Financial Services",
    "manufacturing":        "Manufacturing",
    "professional_services":"Professional Services",
    "ngo_development":      "NGO / Development",
    "technology":           "Technology",
    "hospitality":          "Hospitality",
}


def _serialize_learner(learner: LearnerUser, completed: int, total_events: int) -> dict:
    """Serialize a learner for the list response."""
    initials = "".join(
        w[0].upper()
        for w in learner.stated_goal.split()[:2]
        if w
    ) or learner.user_id[-2:].upper()

    return {
        "user_id":        learner.user_id,
        "initials":       initials,
        "role":           _ROLE_LABELS.get(learner.role, learner.role),
        "seniority":      _SENIORITY_LABELS.get(learner.seniority, learner.seniority),
        "industry":       _INDUSTRY_LABELS.get(learner.industry, learner.industry),
        "company_size":   learner.company_size,
        "stated_goal":    learner.stated_goal,
        "completed_courses": completed,
        "total_events":   total_events,
        "signal_mode":    (
            "cold-start"      if completed == 0
            else "blended"    if completed < 5
            else "behavioral"
        ),
        "usage_confidence": round(min(1.0, completed / 5), 2),
    }


@method_decorator(csrf_exempt, name="dispatch")
class LearnerListView(View):
    """
    GET /api/learners

    Query params:
        page      (int, default 1)
        page_size (int, default 25, max 100)
        search    (str) — filters on user_id, role, industry, stated_goal
        role      (str) — filter by role slug
        signal    (str) — filter by signal_mode: cold-start | blended | behavioral

    Requires: Authorization: Bearer <access_token>

    Returns paginated list of learners with profile stats.
    """

    @jwt_required
    def get(self, request):
        # --- Query params ---
        try:
            page      = max(1, int(request.GET.get("page",      1)))
            page_size = min(100, max(1, int(request.GET.get("page_size", 25))))
        except ValueError:
            return JsonResponse({"error": "page and page_size must be integers"}, status=400)

        search     = request.GET.get("search",  "").strip()
        role_filter   = request.GET.get("role",    "").strip()
        signal_filter = request.GET.get("signal",  "").strip()

        # --- Base queryset ---
        qs = LearnerUser.objects.all()

        if search:
            qs = qs.filter(
                Q(user_id__icontains=search)     |
                Q(stated_goal__icontains=search)  |
                Q(industry__icontains=search)
            )
        if role_filter:
            qs = qs.filter(role=role_filter)

        # Annotate completion counts in a single query
        qs = qs.annotate(
            completed_count=Count(
                "usage_events",
                filter=Q(
                    usage_events__event_type="completed",
                    usage_events__progress_pct__gte=95,
                ),
                distinct=True,
            ),
            total_event_count=Count("usage_events", distinct=True),
        ).order_by("user_id")

        # Signal mode filter (post-annotation)
        if signal_filter == "cold-start":
            qs = qs.filter(completed_count=0)
        elif signal_filter == "blended":
            qs = qs.filter(completed_count__gt=0, completed_count__lt=5)
        elif signal_filter == "behavioral":
            qs = qs.filter(completed_count__gte=5)

        total = qs.count()
        offset = (page - 1) * page_size
        learners = qs[offset: offset + page_size]

        results = [
            _serialize_learner(l, l.completed_count, l.total_event_count)
            for l in learners
        ]

        return JsonResponse({
            "total":     total,
            "page":      page,
            "page_size": page_size,
            "pages":     (total + page_size - 1) // page_size if total else 1,
            "learners":  results,
        })
