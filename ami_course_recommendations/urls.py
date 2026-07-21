"""URL patterns for the ami_course_recommendations app."""

from django.urls import path
from ami_course_recommendations.views import RecommendationsView

urlpatterns = [
    path(
        "users/<str:user_id>/recommendations",
        RecommendationsView.as_view(),
        name="recommendations",
    ),
]
