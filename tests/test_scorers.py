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
    ScoreResult,
    get_all_scorers,
)


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
    
    def test_score_result_is_immutable(self):
        """ScoreResult should be a frozen dataclass (immutable)."""
        result = ScoreResult(score=0.75, weight=0.35, reason_fragment="test")
        
        with self.assertRaises(Exception):  # FrozenInstanceError in practice
            result.score = 0.99
