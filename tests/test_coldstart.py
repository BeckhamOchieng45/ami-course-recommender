"""
Tests for cold-start blending and score aggregation.

Key properties verified:
- Weight redistribution is correct at 0, partial, and full confidence
- Weights always sum to 1.0 (no probability mass lost)
- Cold-start user still gets a non-zero, ranked recommendation
- Active user's recommendations are driven more by usage signal
- Score is monotonically non-decreasing as usage_confidence grows
  (more data should never hurt the overall quality of the signal)
- Breakdown is complete and sums to final_score
"""

from django.test import TestCase
from ami_course_recommendations.models import User, Course, UsageEvent, SurveyResponse
from engine.coldstart import (
    compute_usage_confidence,
    compute_effective_weights,
    aggregate_scores,
    rank_courses,
    K_COLD_START,
    W_USAGE_BASE,
    W_SURVEY_BASE,
    W_CONTEXT_BASE,
    FREED_TO_SURVEY,
    FREED_TO_CONTEXT,
    AggregatedScore,
    ComponentBreakdown,
)


class WeightBlendingTests(TestCase):
    """Unit tests for the cold-start weight redistribution formula."""

    def test_zero_confidence_zeroes_usage_weight(self):
        """At usage_confidence=0, usage effective weight should be 0."""
        w_usage, w_survey, w_context = compute_effective_weights(0.0)
        self.assertAlmostEqual(w_usage, 0.0)

    def test_zero_confidence_redistributes_freed_weight(self):
        """
        At usage_confidence=0, the full W_USAGE_BASE is freed.
        Survey absorbs 60% of it; work-context absorbs 40%.
        """
        w_usage, w_survey, w_context = compute_effective_weights(0.0)
        freed = W_USAGE_BASE  # All usage weight freed
        self.assertAlmostEqual(w_survey, W_SURVEY_BASE + freed * FREED_TO_SURVEY)
        self.assertAlmostEqual(w_context, W_CONTEXT_BASE + freed * FREED_TO_CONTEXT)

    def test_full_confidence_restores_base_weights(self):
        """At usage_confidence=1.0, all three scorers carry their base weights."""
        w_usage, w_survey, w_context = compute_effective_weights(1.0)
        self.assertAlmostEqual(w_usage, W_USAGE_BASE)
        self.assertAlmostEqual(w_survey, W_SURVEY_BASE)
        self.assertAlmostEqual(w_context, W_CONTEXT_BASE)

    def test_weights_always_sum_to_one(self):
        """
        Total weight must equal 1.0 at every confidence level.
        This is a conservation-of-probability-mass invariant.
        """
        for confidence in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
            w_usage, w_survey, w_context = compute_effective_weights(confidence)
            total = w_usage + w_survey + w_context
            self.assertAlmostEqual(
                total, 1.0, places=10,
                msg=f"Weights summed to {total} at confidence={confidence}",
            )

    def test_weight_transition_is_monotonic(self):
        """
        As confidence increases, w_usage should increase and w_survey/w_context
        should decrease monotonically. No discontinuities.
        """
        steps = [i / 10 for i in range(11)]  # 0.0, 0.1, ..., 1.0
        prev_usage = -1.0
        prev_survey = float('inf')
        prev_context = float('inf')

        for confidence in steps:
            w_usage, w_survey, w_context = compute_effective_weights(confidence)
            self.assertGreaterEqual(w_usage, prev_usage,
                msg=f"w_usage not monotone at confidence={confidence}")
            self.assertLessEqual(w_survey, prev_survey,
                msg=f"w_survey not monotone at confidence={confidence}")
            self.assertLessEqual(w_context, prev_context,
                msg=f"w_context not monotone at confidence={confidence}")
            prev_usage, prev_survey, prev_context = w_usage, w_survey, w_context


class UsageConfidenceTests(TestCase):
    """Tests for the usage_confidence computation from DB events."""

    def setUp(self):
        self.user = User.objects.create(
            user_id="COLD-USR-001",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="test",
            true_interest="cash flow management",
        )
        # A course to attach events to
        self.course = Course.objects.create(
            course_id="COLD-CRS-001",
            title="Test Course",
            programme_area="entrepreneurship",
            level="foundational",
            skills_taught=["cash flow forecasting"],
            duration_mins=60,
            prerequisites=[],
            is_paid=False,
        )

    def test_no_events_gives_zero_confidence(self):
        """User with no events should have usage_confidence = 0.0."""
        self.assertAlmostEqual(compute_usage_confidence(self.user), 0.0)

    def test_k_completions_gives_full_confidence(self):
        """Exactly K completed events should yield usage_confidence = 1.0."""
        for i in range(K_COLD_START):
            course = Course.objects.create(
                course_id=f"COLD-CRS-{i+2:03d}",
                title=f"Course {i}",
                programme_area="entrepreneurship",
                level="foundational",
                skills_taught=["bookkeeping basics"],
                duration_mins=60,
                prerequisites=[],
                is_paid=False,
            )
            UsageEvent.objects.create(
                user=self.user,
                course=course,
                event_type="completed",
                progress_pct=90.0,
                quiz_score=75.0,
                timestamp="2025-01-01T10:00:00Z",
            )
        self.assertAlmostEqual(compute_usage_confidence(self.user), 1.0)

    def test_dropped_events_do_not_increase_confidence(self):
        """Dropped events must not count toward usage_confidence."""
        UsageEvent.objects.create(
            user=self.user,
            course=self.course,
            event_type="dropped",
            progress_pct=20.0,
            quiz_score=None,
            timestamp="2025-01-01T10:00:00Z",
        )
        self.assertAlmostEqual(compute_usage_confidence(self.user), 0.0)

    def test_confidence_is_capped_at_one(self):
        """More than K completed events should not push confidence above 1.0."""
        for i in range(K_COLD_START + 5):
            course = Course.objects.create(
                course_id=f"COLD-OVER-{i:03d}",
                title=f"Extra Course {i}",
                programme_area="entrepreneurship",
                level="foundational",
                skills_taught=["bookkeeping basics"],
                duration_mins=60,
                prerequisites=[],
                is_paid=False,
            )
            UsageEvent.objects.create(
                user=self.user,
                course=course,
                event_type="completed",
                progress_pct=95.0,
                quiz_score=80.0,
                timestamp="2025-01-01T10:00:00Z",
            )
        self.assertAlmostEqual(compute_usage_confidence(self.user), 1.0)


class ScoreAggregationTests(TestCase):
    """End-to-end tests for aggregate_scores() and rank_courses()."""

    def setUp(self):
        self.course_match = Course.objects.create(
            course_id="AGG-CRS-001",
            title="Cash Flow Forecasting for Small Businesses",
            programme_area="entrepreneurship",
            level="foundational",
            skills_taught=["cash flow forecasting", "working capital", "liquidity management"],
            duration_mins=90,
            prerequisites=[],
            is_paid=False,
        )
        self.course_nomatch = Course.objects.create(
            course_id="AGG-CRS-002",
            title="AI Strategy for Senior Leaders",
            programme_area="ai_strategy",
            level="advanced",
            skills_taught=["AI for business leaders", "automation strategy"],
            duration_mins=150,
            prerequisites=[],
            is_paid=False,
        )

        # Cold-start user: no usage events, but strong survey signal
        self.cold_user = User.objects.create(
            user_id="AGG-USR-001",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="improve cash flow",
            true_interest="cash flow management",
        )
        SurveyResponse.objects.create(
            user=self.cold_user,
            goals=["cash flow forecasting", "working capital"],
            skill_gaps=["liquidity management"],
            preferred_topics=["bookkeeping basics"],
            confidence_by_topic={"cash flow": 2},
        )

        # Active user: completed a related course
        self.active_user = User.objects.create(
            user_id="AGG-USR-002",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="improve cash flow",
            true_interest="cash flow management",
        )
        SurveyResponse.objects.create(
            user=self.active_user,
            goals=["cash flow forecasting", "working capital"],
            skill_gaps=["liquidity management"],
            preferred_topics=["bookkeeping basics"],
            confidence_by_topic={"cash flow": 2},
        )
        prior_course = Course.objects.create(
            course_id="AGG-CRS-003",
            title="Introduction to Business Bookkeeping",
            programme_area="entrepreneurship",
            level="foundational",
            skills_taught=["bookkeeping basics", "profit and loss statements", "working capital"],
            duration_mins=60,
            prerequisites=[],
            is_paid=False,
        )
        UsageEvent.objects.create(
            user=self.active_user,
            course=prior_course,
            event_type="completed",
            progress_pct=95.0,
            quiz_score=82.0,
            timestamp="2025-01-15T10:00:00Z",
        )

    def test_aggregate_score_returns_aggregated_score_object(self):
        result = aggregate_scores(self.cold_user, self.course_match)
        self.assertIsInstance(result, AggregatedScore)
        self.assertIsInstance(result.course, Course)
        self.assertIsInstance(result.breakdown, list)

    def test_breakdown_contributions_sum_to_final_score(self):
        """Sum of per-component contributions must equal the reported final_score."""
        result = aggregate_scores(self.cold_user, self.course_match)
        contribution_sum = sum(b.contribution for b in result.breakdown)
        self.assertAlmostEqual(result.final_score, contribution_sum, places=5)

    def test_cold_user_has_zero_usage_confidence(self):
        result = aggregate_scores(self.cold_user, self.course_match)
        self.assertAlmostEqual(result.usage_confidence, 0.0)

    def test_active_user_has_nonzero_usage_confidence(self):
        result = aggregate_scores(self.active_user, self.course_match)
        self.assertGreater(result.usage_confidence, 0.0)

    def test_cold_user_still_scores_matched_course(self):
        """
        Cold-start user with strong survey signal should score the matched
        course above zero — survey + work-context carry the load.
        """
        result = aggregate_scores(self.cold_user, self.course_match)
        self.assertGreater(result.final_score, 0.0)

    def test_matched_course_outranks_unrelated_for_cold_user(self):
        """Even without usage history, the matched course should rank higher."""
        score_match = aggregate_scores(self.cold_user, self.course_match).final_score
        score_nomatch = aggregate_scores(self.cold_user, self.course_nomatch).final_score
        self.assertGreater(score_match, score_nomatch)

    def test_primary_reason_is_non_empty(self):
        """Every recommendation should carry a human-readable reason."""
        result = aggregate_scores(self.cold_user, self.course_match)
        self.assertTrue(len(result.primary_reason) > 0)

    def test_rank_courses_returns_sorted_list(self):
        """rank_courses() should return courses sorted descending by final_score."""
        ranked = rank_courses(self.cold_user, [self.course_match, self.course_nomatch])

        self.assertEqual(len(ranked), 2)
        self.assertGreaterEqual(ranked[0].final_score, ranked[1].final_score)
        # Matched course should be first
        self.assertEqual(ranked[0].course.course_id, "AGG-CRS-001")

    def test_all_breakdowns_have_three_components(self):
        """Breakdown should have one entry per registered scorer (currently 3)."""
        result = aggregate_scores(self.cold_user, self.course_match)
        self.assertEqual(len(result.breakdown), 3)

    def test_cold_user_usage_component_is_zero_or_near_zero(self):
        """
        For a cold-start user, the usage component's contribution should be
        very small (cohort may provide a tiny non-zero boost, but the bulk
        of score should come from survey and work-context).
        """
        result = aggregate_scores(self.cold_user, self.course_match)
        usage_breakdown = next(
            (b for b in result.breakdown if b.name == 'score_usage_based'), None
        )
        self.assertIsNotNone(usage_breakdown)
        # Usage confidence is 0, so effective_weight should be 0
        self.assertAlmostEqual(usage_breakdown.effective_weight, 0.0)

    def test_active_user_usage_component_contributes(self):
        """
        For an active user, usage component should have non-zero contribution.
        """
        result = aggregate_scores(self.active_user, self.course_match)
        usage_breakdown = next(
            (b for b in result.breakdown if b.name == 'score_usage_based'), None
        )
        self.assertIsNotNone(usage_breakdown)
        self.assertGreater(usage_breakdown.effective_weight, 0.0)
