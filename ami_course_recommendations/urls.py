"""URL patterns for the ami_course_recommendations app."""

from django.urls import path
from ami_course_recommendations.views import RecommendationsView
from ami_course_recommendations.chat_view import ChatView

urlpatterns = [
    path(
        "users/<str:user_id>/recommendations",
        RecommendationsView.as_view(),
        name="recommendations",
    ),
    path(
        "chat",
        ChatView.as_view(),
        name="chat",
    ),
]
