"""URL configuration for ami_engine project."""

from pathlib import Path
from django.contrib import admin
from django.urls import path, include
from django.http import FileResponse, Http404

_UI_DIR  = Path(__file__).resolve().parent.parent / "ui"


def _serve(filename):
    """Return a view that serves a single HTML file from ui/."""
    def view(request):
        f = _UI_DIR / filename
        if not f.exists():
            raise Http404(f"{filename} not found")
        return FileResponse(open(f, "rb"), content_type="text/html")
    return view


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/",   include("ami_course_recommendations.urls")),

    # ── UI pages ─────────────────────────────────────────────────
    path("login",       _serve("login.html"), name="login"),
    path("",            _serve("index.html"), name="dashboard"),
    path("ui/",         _serve("index.html")),
    path("ui/index.html", _serve("index.html")),
]
