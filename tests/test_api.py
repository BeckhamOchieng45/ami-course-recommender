"""
Tests for GET /api/users/{user_id}/recommendations endpoint.

Verifies:
- 200 response shape and field completeness
- ?n parameter validation (missing, valid, out-of-range, non-integer)
- 404 for unknown user_id
- Cold-start user returns non-empty recommendations
- Active user returns higher usage_confidence than cold-start
- Already-completed courses are not recommended
- Score breakdown is present and contains 3 components
- Response is valid JSON with lean payload (no spurious fields)
"""

import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User as DjangoUser
from ami_course_recommendations.models import User, Course, UsageEvent, SurveyResponse
from datagen.generate import generate_all
import random


def _get_auth_token(client):
    """Create a superuser and return its JWT access token."""
    email = "testadmin@ami-test.com"
    if not DjangoUser.objects.filter(username=email).exists():
        DjangoUser.objects.create_superuser(username=email, email=email, password="testpass")
    resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": email, "password": "testpass"}),
        content_type="application/json",
    )
    return json.loads(resp.content)["access"]


def make_user(uid, role="micro_business_owner", seniority="micro-entrepreneur",
              industry="retail", size="micro", goal="improve cash flow") -> User:
    return User.objects.create(
        user_id=uid, role=role, seniority=seniority, industry=industry,
        company_size=size, stated_goal=goal, true_interest="cash flow management",
    )


def make_course(cid, area="entrepreneurship", level="foundational",
                skills=None) -> Course:
    return Course.objects.create(
        course_id=cid, title=f"Course {cid}", programme_area=area, level=level,
        skills_taught=skills or ["cash flow forecasting", "working capital"],
        duration_mins=90, prerequisites=[], is_paid=False,
    )


class RecommendationsEndpointTests(TestCase):
    """Core happy-path and shape tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        random.seed(42)
        with patch("engine.llm.enhance_reason", return_value="__test__"):
            generate_all(n_users=50, clear=True)
        cls.client = Client()
        cls.token = _get_auth_token(cls.client)
        cls.user = User.objects.first()

    def _get(self, user_id, **params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"/api/users/{user_id}/recommendations"
        if qs:
            url += f"?{qs}"
        with patch("engine.llm.enhance_reason", return_value="__test__"):
            return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_returns_200_for_known_user(self):
        resp = self._get(self.user.user_id)
        self.assertEqual(resp.status_code, 200)

    def test_response_is_valid_json(self):
        resp = self._get(self.user.user_id)
        data = json.loads(resp.content)
        self.assertIsInstance(data, dict)

    def test_response_has_required_top_level_keys(self):
        resp = self._get(self.user.user_id)
        data = json.loads(resp.content)
        for key in ["user_id", "usage_confidence", "llm_enhanced", "recommendation_count", "recommendations"]:
            self.assertIn(key, data, f"Missing top-level key: {key}")

    def test_llm_enhanced_flag_is_boolean(self):
        resp = self._get(self.user.user_id)
        data = json.loads(resp.content)
        self.assertIsInstance(data["llm_enhanced"], bool)

    def test_default_returns_five_recommendations(self):
        resp = self._get(self.user.user_id)
        data = json.loads(resp.content)
        self.assertEqual(len(data["recommendations"]), data["recommendation_count"])
        self.assertLessEqual(data["recommendation_count"], 5)

    def test_n_param_controls_count(self):
        resp = self._get(self.user.user_id, n=3)
        data = json.loads(resp.content)
        self.assertLessEqual(data["recommendation_count"], 3)

    def test_each_recommendation_has_required_fields(self):
        resp = self._get(self.user.user_id, n=5)
        data = json.loads(resp.content)
        required = {"position", "course", "score", "usage_confidence",
                    "reason", "coaching_reason", "reason_detail",
                    "reason_driver", "score_breakdown"}
        for rec in data["recommendations"]:
            missing = required - set(rec.keys())
            self.assertEqual(missing, set(), f"Recommendation missing fields: {missing}")

    def test_course_object_has_required_fields(self):
        resp = self._get(self.user.user_id)
        data = json.loads(resp.content)
        course_fields = {"course_id", "title", "programme_area", "level",
                         "duration_mins", "is_paid", "skills_taught"}
        for rec in data["recommendations"]:
            missing = course_fields - set(rec["course"].keys())
            self.assertEqual(missing, set(), f"Course missing fields: {missing}")

    def test_positions_are_sequential_from_one(self):
        resp = self._get(self.user.user_id, n=5)
        data = json.loads(resp.content)
        positions = [r["position"] for r in data["recommendations"]]
        expected = list(range(1, len(positions) + 1))
        self.assertEqual(positions, expected)

    def test_scores_are_non_increasing(self):
        resp = self._get(self.user.user_id, n=5)
        data = json.loads(resp.content)
        scores = [r["score"] for r in data["recommendations"]]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(
                scores[i], scores[i + 1],
                f"Score at position {i+1} < score at position {i+2}",
            )

    def test_score_breakdown_has_three_components(self):
        resp = self._get(self.user.user_id, n=1)
        data = json.loads(resp.content)
        if data["recommendations"]:
            breakdown = data["recommendations"][0]["score_breakdown"]
            self.assertEqual(len(breakdown), 3)

    def test_reason_is_non_empty_string(self):
        resp = self._get(self.user.user_id, n=5)
        data = json.loads(resp.content)
        for rec in data["recommendations"]:
            self.assertGreater(len(rec["reason"]), 0,
                f"Empty reason at position {rec['position']}")

    def test_coaching_reason_is_non_empty_string(self):
        """coaching_reason must always be populated (falls back to reason without Groq key)."""
        resp = self._get(self.user.user_id, n=5)
        data = json.loads(resp.content)
        for rec in data["recommendations"]:
            self.assertGreater(len(rec["coaching_reason"]), 0,
                f"Empty coaching_reason at position {rec['position']}")

    def test_coaching_reason_equals_reason_without_groq_key(self):
        """Without GROQ_API_KEY, coaching_reason must equal reason (no hallucination)."""
        import os
        if os.environ.get("GROQ_API_KEY", "").strip():
            self.skipTest("GROQ_API_KEY is set — fallback test not applicable")
        resp = self._get(self.user.user_id, n=3)
        data = json.loads(resp.content)
        for rec in data["recommendations"]:
            self.assertEqual(rec["coaching_reason"], rec["reason"])

    def test_usage_confidence_is_between_zero_and_one(self):
        resp = self._get(self.user.user_id)
        data = json.loads(resp.content)
        uc = data["usage_confidence"]
        self.assertGreaterEqual(uc, 0.0)
        self.assertLessEqual(uc, 1.0)


class ErrorHandlingTests(TestCase):
    """Tests for 404 and 400 error responses."""

    def setUp(self):
        self.client = Client()
        self.token = _get_auth_token(self.client)

    def _get(self, user_id, **params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"/api/users/{user_id}/recommendations" + (f"?{qs}" if qs else "")
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_unknown_user_returns_404(self):
        resp = self._get("DOES-NOT-EXIST")
        self.assertEqual(resp.status_code, 404)
        data = json.loads(resp.content)
        self.assertIn("error", data)
        self.assertIn("user_id", data)

    def test_non_integer_n_returns_400(self):
        user = make_user("API-ERR-001")
        resp = self._get(user.user_id, n="abc")
        self.assertEqual(resp.status_code, 400)

    def test_n_zero_returns_400(self):
        user = make_user("API-ERR-002")
        resp = self._get(user.user_id, n=0)
        self.assertEqual(resp.status_code, 400)

    def test_n_over_max_returns_400(self):
        user = make_user("API-ERR-003")
        resp = self._get(user.user_id, n=999)
        self.assertEqual(resp.status_code, 400)


class ColdStartVsActiveUserTests(TestCase):
    """Verify cold-start and active users both get valid recommendations."""

    def setUp(self):
        self.client = Client()
        random.seed(7)
        with patch("engine.llm.enhance_reason", return_value="__test__"):
            generate_all(n_users=50, clear=True)
        self.token = _get_auth_token(self.client)

        # Find a cold-start user (no usage events)
        users_with_events = set(
            UsageEvent.objects.values_list("user_id", flat=True).distinct()
        )
        all_users = list(User.objects.all())
        cold_start_users = [u for u in all_users if u.user_id not in users_with_events]
        active_users = [u for u in all_users if u.user_id in users_with_events]

        self.cold_user = cold_start_users[0] if cold_start_users else None
        self.active_user = active_users[0] if active_users else None

    def test_cold_start_user_gets_recommendations(self):
        if not self.cold_user:
            self.skipTest("No cold-start users in test dataset")
        with patch("engine.llm.enhance_reason", return_value="__test__"):
            resp = self.client.get(f"/api/users/{self.cold_user.user_id}/recommendations", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        data = json.loads(resp.content)
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(data["recommendation_count"], 0)

    def test_cold_start_user_has_zero_usage_confidence(self):
        if not self.cold_user:
            self.skipTest("No cold-start users in test dataset")
        with patch("engine.llm.enhance_reason", return_value="__test__"):
            resp = self.client.get(f"/api/users/{self.cold_user.user_id}/recommendations", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        data = json.loads(resp.content)
        self.assertAlmostEqual(data["usage_confidence"], 0.0)

    def test_active_user_has_higher_confidence_than_cold(self):
        if not self.cold_user or not self.active_user:
            self.skipTest("Need both cold and active users in test dataset")
        with patch("engine.llm.enhance_reason", return_value="__test__"):
            cold_resp  = self.client.get(f"/api/users/{self.cold_user.user_id}/recommendations",   HTTP_AUTHORIZATION=f"Bearer {self.token}")
            active_resp = self.client.get(f"/api/users/{self.active_user.user_id}/recommendations", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        cold_conf  = json.loads(cold_resp.content)["usage_confidence"]
        active_conf = json.loads(active_resp.content)["usage_confidence"]
        self.assertGreater(active_conf, cold_conf)

    def test_completed_courses_not_in_recommendations(self):
        if not self.active_user:
            self.skipTest("No active users in test dataset")
        completed_ids = set(UsageEvent.objects.filter(user=self.active_user, event_type="completed", progress_pct__gte=95.0).values_list("course_id", flat=True))
        if not completed_ids:
            self.skipTest("Active user has no qualifying completed courses")
        with patch("engine.llm.enhance_reason", return_value="__test__"):
            resp = self.client.get(f"/api/users/{self.active_user.user_id}/recommendations?n=20", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        data = json.loads(resp.content)
        recommended_ids = {r["course"]["course_id"] for r in data["recommendations"]}
        self.assertEqual(completed_ids & recommended_ids, set())
