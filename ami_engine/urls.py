"""
URL configuration for ami_engine project.
"""

from pathlib import Path
from django.contrib import admin
from django.urls import path, include
from django.http import FileResponse, Http404

_UI_FILE = Path(__file__).resolve().parent.parent / "ui" / "index.html"


def serve_ui(request):
    """Serve the single-page UI directly — works in dev without collectstatic."""
    if not _UI_FILE.exists():
        raise Http404("UI file not found")
    return FileResponse(open(_UI_FILE, "rb"), content_type="text/html")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("ami_course_recommendations.urls")),
    # All of these serve the same single HTML file
    path("", serve_ui),
    path("ui/", serve_ui),
    path("ui/index.html", serve_ui),
]
