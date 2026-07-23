"""
Tests for JWT authentication and learner-list endpoints.

- POST /api/auth/login  — valid creds return tokens, invalid return 401
- POST /api/auth/refresh — valid refresh returns new access token
- GET  /api/auth/me     — returns profile for authenticated user
- GET  /api/learners    — paginated list, search, signal filter
- Recommendations/chat endpoints return 401 without a token
"""

import json
from django.test import TestCase, Client
from django.contrib.auth.models import User as DjangoUser
from ami_course_recommendations.models import User as LearnerUser, UsageEvent, Course


def make_django_user(email="test@ami.com", password="testpass123"):
    return DjangoUser.objects.create_superuser(
        username=email, email=email, password=password
    )


def make_learner(uid, role="micro_business_owner", industry="retail", completed=0):
    u = LearnerUser.objects.create(
        user_id=uid, role=role, seniority="micro-entrepreneur",
        industry=industry, company_size="micro",
        stated_goal="improve cash flow", true_interest="cash flow management",
    )
    if completed:
        c = Course.objects.create(
            course_id=f"C-{uid}", title=f"Course {uid}",
            programme_area="entrepreneurship", level="foundational",
            skills_taught=["cash flow forecasting"], duration_mins=60,
            prerequisites=[], is_paid=False,
        )
        for i in range(completed):
            cobj = Course.objects.create(
                course_id=f"C-{uid}-{i}", title=f"Filler {uid} {i}",
                programme_area="entrepreneurship", level="foundational",
                skills_taught=["bookkeeping basics"], duration_mins=60,
                prerequisites=[], is_paid=False,
            )
            UsageEvent.objects.create(
                user=u, course=cobj, event_type="completed",
                progress_pct=96.0, quiz_score=75.0,
                timestamp="2025-01-01T10:00:00Z",
            )
    return u


def get_token(client, email="admin@test.com", password="testpass123"):
    resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": email, "password": password}),
        content_type="application/json",
    )
    return json.loads(resp.content).get("access", "")


class LoginViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_django_user("admin@test.com", "testpass123")

    def test_valid_credentials_return_tokens(self):
        resp = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": "admin@test.com", "password": "testpass123"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertIn("user", data)

    def test_user_payload_has_expected_fields(self):
        resp = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": "admin@test.com", "password": "testpass123"}),
            content_type="application/json",
        )
        user = json.loads(resp.content)["user"]
        for field in ["id", "email", "name", "is_staff"]:
            self.assertIn(field, user)

    def test_invalid_password_returns_401(self):
        resp = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": "admin@test.com", "password": "wrong"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_unknown_email_returns_401(self):
        resp = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": "nobody@test.com", "password": "pass"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_missing_fields_returns_400(self):
        resp = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": "admin@test.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_email_match_by_email_field(self):
        """Login should work when email field differs from username."""
        DjangoUser.objects.create_user(
            username="differentusername", email="other@test.com", password="pass123"
        )
        resp = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": "other@test.com", "password": "pass123"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)


class TokenRefreshViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        make_django_user("refresh@test.com", "testpass123")

    def test_valid_refresh_returns_new_access(self):
        login_resp = self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": "refresh@test.com", "password": "testpass123"}),
            content_type="application/json",
        )
        refresh_token = json.loads(login_resp.content)["refresh"]
        resp = self.client.post(
            "/api/auth/refresh",
            data=json.dumps({"refresh": refresh_token}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", json.loads(resp.content))

    def test_invalid_refresh_returns_401(self):
        resp = self.client.post(
            "/api/auth/refresh",
            data=json.dumps({"refresh": "not-a-real-token"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)


class MeViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        make_django_user("me@test.com", "testpass123")
        self.token = get_token(self.client, "me@test.com", "testpass123")

    def test_me_returns_profile(self):
        resp = self.client.get(
            "/api/auth/me",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["email"], "me@test.com")

    def test_me_without_token_returns_401(self):
        resp = self.client.get("/api/auth/me")
        self.assertEqual(resp.status_code, 401)

    def test_me_with_bad_token_returns_401(self):
        resp = self.client.get(
            "/api/auth/me", HTTP_AUTHORIZATION="Bearer garbage"
        )
        self.assertEqual(resp.status_code, 401)


class LearnerListViewTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        make_django_user("admin@learner-test.com", "testpass123")
        make_learner("LRN-001", "micro_business_owner", "retail",    completed=0)
        make_learner("LRN-002", "sme_manager",          "agriculture",completed=3)
        make_learner("LRN-003", "senior_executive",     "technology", completed=6)
        make_learner("LRN-004", "corporate_employee",   "retail",     completed=0)
        cls.client = Client()
        cls.token = get_token(cls.client, "admin@learner-test.com", "testpass123")

    def _get(self, **params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = "/api/learners" + (f"?{qs}" if qs else "")
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_returns_200_with_token(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)

    def test_returns_401_without_token(self):
        resp = self.client.get("/api/learners")
        self.assertEqual(resp.status_code, 401)

    def test_response_has_pagination_fields(self):
        data = json.loads(self._get().content)
        for field in ["total", "page", "page_size", "pages", "learners"]:
            self.assertIn(field, data)

    def test_learner_has_required_fields(self):
        data = json.loads(self._get().content)
        self.assertGreater(len(data["learners"]), 0)
        learner = data["learners"][0]
        for field in ["user_id", "display_name", "initials", "role", "industry",
                      "stated_goal", "completed_courses", "signal_mode", "usage_confidence"]:
            self.assertIn(field, learner, f"Missing field: {field}")

    def test_display_name_is_human_readable(self):
        """display_name should be 'Role #N', not a raw user_id."""
        data = json.loads(self._get().content)
        for l in data["learners"]:
            self.assertNotRegex(l["display_name"], r"^USR-",
                "display_name should not be a raw user ID")
            self.assertIn("#", l["display_name"],
                "display_name should contain a # number")

    def test_signal_mode_cold_start_filter(self):
        data = json.loads(self._get(signal="cold-start").content)
        for l in data["learners"]:
            self.assertEqual(l["signal_mode"], "cold-start")
            self.assertEqual(l["completed_courses"], 0)

    def test_signal_mode_blended_filter(self):
        data = json.loads(self._get(signal="blended").content)
        for l in data["learners"]:
            self.assertEqual(l["signal_mode"], "blended")
            self.assertGreater(l["completed_courses"], 0)
            self.assertLess(l["completed_courses"], 5)

    def test_signal_mode_behavioral_filter(self):
        data = json.loads(self._get(signal="behavioral").content)
        for l in data["learners"]:
            self.assertEqual(l["signal_mode"], "behavioral")
            self.assertGreaterEqual(l["completed_courses"], 5)

    def test_industry_search(self):
        data = json.loads(self._get(search="technology").content)
        for l in data["learners"]:
            self.assertIn("technology", l["industry"].lower())

    def test_usage_confidence_correct(self):
        data = json.loads(self._get(signal="behavioral").content)
        for l in data["learners"]:
            self.assertAlmostEqual(l["usage_confidence"], 1.0)

    def test_cold_start_usage_confidence_zero(self):
        data = json.loads(self._get(signal="cold-start").content)
        for l in data["learners"]:
            self.assertAlmostEqual(l["usage_confidence"], 0.0)

    def test_pagination_page_size(self):
        data = json.loads(self._get(page_size=2).content)
        self.assertLessEqual(len(data["learners"]), 2)


class JwtGuardTests(TestCase):
    """Recommendations and chat endpoints must return 401 without a token."""

    def setUp(self):
        self.client = Client()
        make_learner("GUARD-001")

    def test_recommendations_without_token_returns_401(self):
        resp = self.client.get("/api/users/GUARD-001/recommendations")
        self.assertEqual(resp.status_code, 401)

    def test_chat_without_token_returns_401(self):
        resp = self.client.post(
            "/api/chat",
            data=json.dumps({"user_id": "GUARD-001", "question": "test",
                             "recommendation": {}, "history": []}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
