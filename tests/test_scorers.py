"""
Tests for scoring components.

Each scorer is tested with hand-constructed user/course pairs where the
expected relative ranking is known. This is the key verification that the
engine logic is correct, not just that it runs without crashing.
"""

from django.test import TestCase
from ami_course_recommendations.models import User, Course, SurveyResponse
from engine.scorers import (
    score_survey_match,
    score_usage_based,
    score_work_context,
    ScoreResult,
    get_all_scorers,
    SENIORITY_LEVEL_PREFERENCES,
    INDUSTRY_PROGRAMME_AFFINITY,
)
from ami_course_recommendations.models import UsageEvent


class SurveyMatchScorerTests(TestCase):
    """Tests for the survey-based content matching scorer."""
    
    def setUp(self):
        """Create test users and courses with known overlap."""
        # Course 1: Cash flow management content
        self.course_cashflow = Course.objects.create(
            course_id="TEST-001",
            title="Cash Flow Forecasting for Small Businesses",
            programme_area="entrepreneurship",
            level="foundational",
            skills_taught=["cash flow forecasting", "working capital", "liquidity management"],
            duration_mins=90,
            prerequisites=[],
            is_paid=False,
        )
        
        # Course 2: Leadership content (no overlap with cash flow)
        self.course_leadership = Course.objects.create(
            course_id="TEST-002",
            title="Team Management Fundamentals",
            programme_area="leadership",
            level="intermediate",
            skills_taught=["delegation frameworks", "team structures", "performance reviews"],
            duration_mins=120,
            prerequisites=[],
            is_paid=False,
        )
        
        # User 1: Strong interest in cash flow (should match course 1, not 2)
        self.user_cashflow = User.objects.create(
            user_id="TEST-USER-001",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="improve my cash flow management",
            true_interest="cash flow management",
        )
        
        SurveyResponse.objects.create(
            user=self.user_cashflow,
            goals=["cash flow forecasting", "working capital"],
            skill_gaps=["liquidity management"],
            preferred_topics=["bookkeeping basics"],
            confidence_by_topic={"cash flow management": 2, "financial planning": 3},
        )
        
        # User 2: Interest in leadership (should match course 2, not 1)
        self.user_leadership = User.objects.create(
            user_id="TEST-USER-002",
            role="sme_manager",
            industry="manufacturing",
            company_size="small",
            seniority="sme-manager",
            stated_goal="build a high-performing team",
            true_interest="team management and delegation",
        )
        
        SurveyResponse.objects.create(
            user=self.user_leadership,
            goals=["delegation frameworks", "team structures"],
            skill_gaps=["performance reviews"],
            preferred_topics=["coaching conversations"],
            confidence_by_topic={"team management": 2, "leadership": 3},
        )
        
        # User 3: No survey data (cold-start with only work context)
        self.user_no_survey = User.objects.create(
            user_id="TEST-USER-003",
            role="corporate_employee",
            industry="technology",
            company_size="large",
            seniority="early-career",
            stated_goal="improve productivity",
            true_interest="productivity and time management",
        )
        # Deliberately do NOT create SurveyResponse for this user
    
    def test_perfect_match_scores_high(self):
        """User interested in cash flow should score high on cash flow course."""
        result = score_survey_match(self.user_cashflow, self.course_cashflow)
        
        self.assertIsInstance(result, ScoreResult)
        self.assertGreater(result.score, 0.5, "Perfect match should score >0.5")
        self.assertEqual(result.weight, 0.35, "Survey weight should be 0.35 per design")
        self.assertIn("cash flow", result.reason_fragment.lower())
    
    def test_no_match_scores_low(self):
        """User interested in cash flow should score low on leadership course."""
        result = score_survey_match(self.user_cashflow, self.course_leadership)
        
        self.assertLess(result.score, 0.3, "No-match should score <0.3")
    
    def test_asymmetric_matches_score_correctly(self):
        """
        Leadership user should match leadership course >> cash flow course.
        Verifies relative ranking, not just absolute scores.
        """
        score_leadership = score_survey_match(
            self.user_leadership, self.course_leadership
        ).score
        score_cashflow = score_survey_match(
            self.user_leadership, self.course_cashflow
        ).score
        
        self.assertGreater(
            score_leadership,
            score_cashflow + 0.3,
            "Leadership user should strongly prefer leadership course",
        )
    
    def test_no_survey_returns_zero(self):
        """User without survey data should return zero score."""
        result = score_survey_match(self.user_no_survey, self.course_cashflow)
        
        self.assertEqual(result.score, 0.0)
        self.assertIn("no survey", result.reason_fragment.lower())
    
    def test_goals_weighted_higher_than_preferences(self):
        """
        Tags from 'goals' field should contribute more than 'preferred_topics'.
        
        Design decision: stated intent ('I want to learn X') is a stronger
        signal than passive preference ('I'm interested in X').
        """
        # Create two users: one with match in goals, one with match in preferred_topics
        user_goal_match = User.objects.create(
            user_id="TEST-USER-GOAL",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="test",
            true_interest="cash flow",
        )
        SurveyResponse.objects.create(
            user=user_goal_match,
            goals=["cash flow forecasting"],  # Match here
            skill_gaps=[],
            preferred_topics=["unrelated topic A", "unrelated topic B"],
            confidence_by_topic={},
        )
        
        user_pref_match = User.objects.create(
            user_id="TEST-USER-PREF",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="test",
            true_interest="cash flow",
        )
        SurveyResponse.objects.create(
            user=user_pref_match,
            goals=["unrelated topic C", "unrelated topic D"],
            skill_gaps=[],
            preferred_topics=["cash flow forecasting"],  # Match here
            confidence_by_topic={},
        )
        
        score_goal = score_survey_match(user_goal_match, self.course_cashflow).score
        score_pref = score_survey_match(user_pref_match, self.course_cashflow).score
        
        self.assertGreater(
            score_goal,
            score_pref,
            "Goal match should score higher than preference match",
        )
    
    def test_reason_fragment_mentions_matched_tag(self):
        """Reason should reference the actual matched skill, not generic text."""
        result = score_survey_match(self.user_cashflow, self.course_cashflow)
        
        reason_lower = result.reason_fragment.lower()
        # Should mention one of the matched skills
        has_specific_match = any(
            skill in reason_lower
            for skill in ["cash flow", "working capital", "liquidity"]
        )
        self.assertTrue(
            has_specific_match,
            f"Reason should mention a specific matched skill; got: {result.reason_fragment}",
        )
    
    def test_scorer_is_registered(self):
        """Verify score_survey_match is in the global scorer registry."""
        all_scorers = get_all_scorers()
        self.assertIn(
            score_survey_match,
            all_scorers,
            "score_survey_match should be registered via @register_scorer",
        )


class ScorerArchitectureTests(TestCase):
    """Tests for the pluggable scorer registry pattern."""
    
    def test_scorers_can_be_listed(self):
        """get_all_scorers() should return all registered scorers."""
        scorers = get_all_scorers()
        self.assertIsInstance(scorers, list)
        self.assertGreater(len(scorers), 0, "At least one scorer should be registered")
    
    def test_all_three_scorers_are_registered(self):
        """All three core scorers must be in the registry."""
        scorers = get_all_scorers()
        self.assertIn(score_survey_match, scorers)
        self.assertIn(score_usage_based, scorers)
        self.assertIn(score_work_context, scorers)
    
    def test_score_result_is_immutable(self):
        """ScoreResult should be a frozen dataclass (immutable)."""
        result = ScoreResult(score=0.75, weight=0.35, reason_fragment="test")
        
        with self.assertRaises(Exception):  # FrozenInstanceError in practice
            result.score = 0.99


class UsageBasedScorerTests(TestCase):
    """Tests for usage-based content similarity + cohort popularity scorer."""

    def setUp(self):
        """Create courses, users, and usage events with known relationships."""
        # Two courses in the same domain (entrepreneurship / cash flow)
        self.course_cashflow_intro = Course.objects.create(
            course_id="USAGE-001",
            title="Introduction to Business Bookkeeping",
            programme_area="entrepreneurship",
            level="foundational",
            skills_taught=["bookkeeping basics", "profit and loss statements", "financial record-keeping"],
            duration_mins=60,
            prerequisites=[],
            is_paid=False,
        )
        self.course_cashflow_advanced = Course.objects.create(
            course_id="USAGE-002",
            title="Cash Flow Forecasting for Small Businesses",
            programme_area="entrepreneurship",
            level="foundational",
            skills_taught=["cash flow forecasting", "profit and loss statements", "working capital"],
            duration_mins=90,
            prerequisites=[],
            is_paid=False,
        )
        # Course in a completely unrelated domain
        self.course_ai = Course.objects.create(
            course_id="USAGE-003",
            title="AI Fundamentals for Business Leaders",
            programme_area="ai_strategy",
            level="advanced",
            skills_taught=["AI for business leaders", "automation strategy", "data-driven decision-making"],
            duration_mins=120,
            prerequisites=[],
            is_paid=False,
        )

        # User who completed the intro bookkeeping course with high scores
        self.active_user = User.objects.create(
            user_id="USAGE-USR-001",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="understand my numbers",
            true_interest="financial planning and bookkeeping",
        )
        UsageEvent.objects.create(
            user=self.active_user,
            course=self.course_cashflow_intro,
            event_type="completed",
            progress_pct=95.0,
            quiz_score=78.0,
            timestamp="2025-01-15T10:00:00Z",
        )

        # Cohort user (same role/industry/seniority) who completed the advanced course
        self.cohort_user = User.objects.create(
            user_id="USAGE-USR-002",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="understand my numbers",
            true_interest="financial planning and bookkeeping",
        )
        UsageEvent.objects.create(
            user=self.cohort_user,
            course=self.course_cashflow_advanced,
            event_type="completed",
            progress_pct=92.0,
            quiz_score=82.0,
            timestamp="2025-01-20T10:00:00Z",
        )

        # Cold-start user: no usage history
        self.cold_user = User.objects.create(
            user_id="USAGE-USR-003",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="understand my numbers",
            true_interest="financial planning and bookkeeping",
        )

    def test_similar_course_scores_higher_than_unrelated(self):
        """
        Course with overlapping tags to completed courses should score higher
        than a course in an entirely different domain.
        """
        score_similar = score_usage_based(self.active_user, self.course_cashflow_advanced).score
        score_unrelated = score_usage_based(self.active_user, self.course_ai).score

        self.assertGreater(
            score_similar,
            score_unrelated,
            "Course similar to completed history should outscore unrelated course",
        )

    def test_cold_start_user_returns_nonzero_via_cohort(self):
        """
        A cold-start user with no usage history should still get a non-zero score
        via the cohort popularity sub-signal.

        This is the cold-start bridge: cohort popularity provides signal when
        personal usage history is absent.
        """
        result = score_usage_based(self.cold_user, self.course_cashflow_advanced)

        self.assertGreater(
            result.score,
            0.0,
            "Cold-start user should receive nonzero score via cohort popularity",
        )

    def test_cold_start_reason_mentions_cohort(self):
        """Cold-start reason should reference cohort, not personal history."""
        result = score_usage_based(self.cold_user, self.course_cashflow_advanced)

        if result.score > 0:
            self.assertIn(
                "popular",
                result.reason_fragment.lower(),
                f"Cold-start reason should mention cohort popularity; got: {result.reason_fragment}",
            )

    def test_low_engagement_events_are_not_rewarded(self):
        """
        Dropped / low-progress events should not drive content similarity.
        Only completed, high-engagement events are signal.
        """
        low_engagement_user = User.objects.create(
            user_id="USAGE-USR-004",
            role="sme_manager",
            industry="manufacturing",
            company_size="small",
            seniority="sme-manager",
            stated_goal="understand finance",
            true_interest="financial planning and bookkeeping",
        )
        # Only a dropped event — should not count as evidence of interest
        UsageEvent.objects.create(
            user=low_engagement_user,
            course=self.course_cashflow_intro,
            event_type="dropped",
            progress_pct=15.0,
            quiz_score=None,
            timestamp="2025-01-10T10:00:00Z",
        )

        score_low = score_usage_based(low_engagement_user, self.course_cashflow_advanced).score
        score_active = score_usage_based(self.active_user, self.course_cashflow_advanced).score

        self.assertLess(
            score_low,
            score_active,
            "Dropped courses should contribute less to content similarity than completed ones",
        )

    def test_usage_scorer_weight_is_correct(self):
        """Usage scorer base weight should be 0.40 per design document."""
        result = score_usage_based(self.active_user, self.course_cashflow_advanced)
        self.assertEqual(result.weight, 0.40)

    def test_score_is_bounded_zero_to_one(self):
        """All scorer outputs must be in [0, 1]."""
        for course in [self.course_cashflow_intro, self.course_cashflow_advanced, self.course_ai]:
            result = score_usage_based(self.active_user, course)
            self.assertGreaterEqual(result.score, 0.0, f"Score < 0 for {course.course_id}")
            self.assertLessEqual(result.score, 1.0, f"Score > 1 for {course.course_id}")


class WorkContextScorerTests(TestCase):
    """Tests for seniority-level + industry-programme affinity scorer."""

    def setUp(self):
        """Create users at different seniority levels and courses at matching levels."""
        self.course_foundational = Course.objects.create(
            course_id="CTXT-001",
            title="Introduction to Business Bookkeeping",
            programme_area="entrepreneurship",
            level="foundational",
            skills_taught=["bookkeeping basics", "financial record-keeping"],
            duration_mins=60,
            prerequisites=[],
            is_paid=False,
        )
        self.course_advanced_leadership = Course.objects.create(
            course_id="CTXT-002",
            title="Strategic Leadership for Senior Managers",
            programme_area="leadership",
            level="advanced",
            skills_taught=["strategic leadership", "executive presence", "decision frameworks"],
            duration_mins=180,
            prerequisites=[],
            is_paid=False,
        )
        self.course_ai_advanced = Course.objects.create(
            course_id="CTXT-003",
            title="Building an AI Strategy for Your Organisation",
            programme_area="ai_strategy",
            level="advanced",
            skills_taught=["AI for business leaders", "digital transformation roadmap"],
            duration_mins=150,
            prerequisites=[],
            is_paid=False,
        )

        self.micro_entrepreneur = User.objects.create(
            user_id="CTXT-USR-001",
            role="micro_business_owner",
            industry="retail",
            company_size="micro",
            seniority="micro-entrepreneur",
            stated_goal="keep proper records",
            true_interest="financial planning and bookkeeping",
        )
        self.senior_exec = User.objects.create(
            user_id="CTXT-USR-002",
            role="senior_executive",
            industry="technology",
            company_size="large",
            seniority="senior-leader",
            stated_goal="build AI strategy",
            true_interest="AI strategy and digital transformation",
        )

    def test_foundational_course_scores_high_for_micro_entrepreneur(self):
        """Micro-entrepreneur should score high on foundational entrepreneurship content."""
        result = score_work_context(self.micro_entrepreneur, self.course_foundational)
        self.assertGreater(result.score, 0.6)

    def test_advanced_leadership_scores_high_for_senior_exec(self):
        """Senior executive should score high on advanced leadership content."""
        result = score_work_context(self.senior_exec, self.course_advanced_leadership)
        self.assertGreater(result.score, 0.6)

    def test_seniority_level_mismatch_is_soft_penalty_not_zero(self):
        """
        Level mismatch should reduce score, not zero it out.

        This is the deliberate design choice that prevents 'entry-level users
        getting only beginner courses regardless of stated goals' — a strong
        survey/usage signal elsewhere can still outweigh a level mismatch.
        """
        # Micro-entrepreneur given an advanced course — mismatch, but not zero
        result = score_work_context(self.micro_entrepreneur, self.course_advanced_leadership)

        self.assertGreater(result.score, 0.0, "Level mismatch should not produce zero score")
        self.assertLess(result.score, 0.65, "Level mismatch should reduce score below good-match threshold")

    def test_industry_affinity_increases_score(self):
        """
        Tech senior exec should score higher on AI strategy course than on
        a programme area with no industry affinity.
        """
        score_ai = score_work_context(self.senior_exec, self.course_ai_advanced).score
        score_general = score_work_context(self.senior_exec, self.course_foundational).score

        self.assertGreater(
            score_ai,
            score_general,
            "Tech executive should prefer AI strategy course over unrelated foundational content",
        )

    def test_work_context_scorer_weight_is_correct(self):
        """Work-context scorer base weight should be 0.25 per design document."""
        result = score_work_context(self.micro_entrepreneur, self.course_foundational)
        self.assertEqual(result.weight, 0.25)

    def test_score_is_bounded_zero_to_one(self):
        """All scorer outputs must be in [0, 1]."""
        for user in [self.micro_entrepreneur, self.senior_exec]:
            for course in [self.course_foundational, self.course_advanced_leadership, self.course_ai_advanced]:
                result = score_work_context(user, course)
                self.assertGreaterEqual(result.score, 0.0)
                self.assertLessEqual(result.score, 1.0)

    def test_reason_is_informative_on_good_match(self):
        """Reason should mention seniority or industry on a strong match."""
        result = score_work_context(self.senior_exec, self.course_advanced_leadership)

        if result.score > 0.6:
            self.assertTrue(
                len(result.reason_fragment) > 0,
                "Strong context match should produce a non-empty reason",
            )
