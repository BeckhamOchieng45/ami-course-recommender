"""URL patterns for the ami_course_recommendations app."""

from django.urls import path
from ami_course_recommendations.views import RecommendationsView
from ami_course_recommendations.chat_view import ChatView
from ami_course_recommendations.auth_views import (
    LoginView,
    TokenRefreshView,
    MeView,
    LearnerListView,
)

urlpatterns = [
    # ── Recommendations & chat ────────────────────────────────────
    path(
        "users/<str:user_id>/recommendations",
        RecommendationsView.as_view(),
        name="recommendations",
    ),
    path("chat", ChatView.as_view(), name="chat"),

    # ── Auth ──────────────────────────────────────────────────────
    path("auth/login",   LoginView.as_view(),        name="auth-login"),
    path("auth/refresh", TokenRefreshView.as_view(),  name="auth-refresh"),
    path("auth/me",      MeView.as_view(),             name="auth-me"),

    # ── Learners ──────────────────────────────────────────────────
    path("learners", LearnerListView.as_view(), name="learner-list"),
]
