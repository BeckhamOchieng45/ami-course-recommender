"""
Tests for synthetic data generator.

Verifies the hidden true_interest correlation structure and key distribution
properties. The test database is empty at startup, so setUpClass generates
a small but representative dataset (100 users) rather than the full 1,000.
"""

import random
from django.test import TestCase
from django.db.models import Count

from ami_course_recommendations.models import Course, User, UsageEvent, SurveyResponse
from datagen.generate import (
    TRUE_INTEREST_DOMAINS,
    DOMAIN_TO_SKILLS,
    DOMAIN_TO_PROGRAMME,
    build_users,
    build_survey,
    build_usage_events,
    build_courses_by_domain,
    generate_all,
)

# Use a reduced dataset for tests — fast but still representative
TEST_USER_COUNT = 100


class DataGeneratorSchemaTests(TestCase):
    """
    Tests that run against a freshly generated test dataset.
    Calls generate_all() once per class, not per test.
    """

    @classmethod
    def setUpClass(cls):
        """Generate a small representative dataset for the test run."""
        super().setUpClass()
        random.seed(99)  # Reproducible for CI
        generate_all(n_users=TEST_USER_COUNT, clear=True)

    # ------------------------------------------------------------------ #
    # Record counts and existence                                          #
    # ------------------------------------------------------------------ #

    def test_courses_generated(self):
        """Generator should produce courses in the expected range."""
        count = Course.objects.count()
        self.assertGreater(count, 50, "Expected at least 50 courses")
        self.assertLess(count, 200, "Expected fewer than 200 courses")

    def test_users_generated(self):
        """Generator should create exactly TEST_USER_COUNT users."""
        self.assertEqual(User.objects.count(), TEST_USER_COUNT)

    def test_every_user_has_a_survey(self):
        """Every user should have exactly one SurveyResponse row."""
        self.assertEqual(
            SurveyResponse.objects.count(),
            User.objects.count(),
        )

    def test_usage_events_generated(self):
        """With 100 users and ~80% active, we should see several hundred events."""
        self.assertGreater(UsageEvent.objects.count(), 100)

    # ------------------------------------------------------------------ #
    # AMI-specific distributions                                           #
    # ------------------------------------------------------------------ #

    def test_course_programme_areas_are_ami_specific(self):
        """Courses must use AMI's programme area labels, not generic categories."""
        allowed = {
            'entrepreneurship', 'leadership', 'workplace',
            'ai_strategy', 'womens_leadership',
        }
        actual = set(Course.objects.values_list('programme_area', flat=True).distinct())

        self.assertTrue(
            actual.issubset(allowed),
            f"Unexpected programme areas found: {actual - allowed}",
        )
        self.assertGreaterEqual(len(actual), 3, "Should span at least 3 programme areas")

    def test_users_have_ami_roles(self):
        """User roles must match AMI's learner taxonomy."""
        allowed = {
            'micro_business_owner', 'sme_manager',
            'corporate_employee', 'senior_executive',
        }
        actual = set(User.objects.values_list('role', flat=True).distinct())
        self.assertTrue(actual.issubset(allowed), f"Unexpected roles: {actual - allowed}")

    def test_micro_sme_majority(self):
        """
        Micro + SME users should exceed 50% of population, reflecting
        AMI's actual learner base where micro/SME is the dominant segment.
        """
        total = User.objects.count()
        micro_sme = User.objects.filter(
            role__in=['micro_business_owner', 'sme_manager']
        ).count()
        self.assertGreater(micro_sme / total, 0.50)

    # ------------------------------------------------------------------ #
    # Course data quality                                                  #
    # ------------------------------------------------------------------ #

    def test_course_skills_are_multiword_and_practical(self):
        """
        Skills taught should be specific multi-word tags like
        'cash flow forecasting', NOT single abstract words like 'finance'.
        """
        courses = list(Course.objects.all())
        practical = 0

        for course in courses:
            if any(len(skill.split()) >= 2 for skill in course.skills_taught):
                practical += 1

        rate = practical / len(courses)
        self.assertGreater(
            rate, 0.80,
            f"Expected >80% of courses to have multi-word skill tags; got {rate:.0%}",
        )

    def test_prerequisite_courses_exist(self):
        """Every prerequisite course_id must point to an existing course."""
        all_ids = set(Course.objects.values_list('course_id', flat=True))
        for course in Course.objects.exclude(prerequisites=[]):
            for prereq_id in course.prerequisites:
                self.assertIn(
                    prereq_id,
                    all_ids,
                    f"Prerequisite {prereq_id} referenced by {course.course_id} does not exist",
                )

    # ------------------------------------------------------------------ #
    # Usage event quality                                                  #
    # ------------------------------------------------------------------ #

    def test_completed_events_have_quiz_scores(self):
        """All completed events must carry a quiz score (0–100)."""
        bad = UsageEvent.objects.filter(event_type='completed', quiz_score__isnull=True)
        self.assertEqual(bad.count(), 0, "Completed events must have quiz scores")

    def test_dropped_events_have_no_quiz_scores(self):
        """Dropped events must not have quiz scores — the quiz wasn't reached."""
        bad = UsageEvent.objects.filter(event_type='dropped').exclude(quiz_score__isnull=True)
        self.assertEqual(bad.count(), 0, "Dropped events must not have quiz scores")

    def test_drop_rate_is_realistic(self):
        """
        Drop rate should fall in the 10–40% range.
        Reflects mobile/connectivity constraints without being implausible.
        """
        completed = UsageEvent.objects.filter(event_type='completed').count()
        dropped = UsageEvent.objects.filter(event_type='dropped').count()
        total = completed + dropped

        if total == 0:
            self.skipTest("No usage events generated — skipping drop-rate check")

        rate = dropped / total
        self.assertGreater(rate, 0.10, f"Drop rate {rate:.1%} is unrealistically low")
        self.assertLess(rate, 0.40, f"Drop rate {rate:.1%} is unrealistically high")

    # ------------------------------------------------------------------ #
    # Cold-start and heavy-user cohorts                                    #
    # ------------------------------------------------------------------ #

    def test_cold_start_cohort_exists(self):
        """
        Roughly 10–35% of users should have zero usage events.
        These users exercise the cold-start path of the recommendation engine.
        """
        users_with_events = set(
            UsageEvent.objects.values_list('user_id', flat=True).distinct()
        )
        total = User.objects.count()
        cold_count = total - len(users_with_events)
        rate = cold_count / total

        self.assertGreater(rate, 0.05, f"Cold-start rate {rate:.1%} is too low to test")
        self.assertLess(rate, 0.40, f"Cold-start rate {rate:.1%} is unexpectedly high")

    def test_heavy_user_cohort_exists(self):
        """
        Some users should have 8+ events (heavy-usage cohort).
        These exercise the behavior-driven path of the recommendation engine.
        """
        counts = (
            UsageEvent.objects
            .values('user_id')
            .annotate(n=Count('event_id'))
            .filter(n__gte=8)
        )
        self.assertGreater(counts.count(), 0, "Expected at least one heavy user (8+ events)")

    # ------------------------------------------------------------------ #
    # Hidden-interest correlation (key quality gate)                       #
    # ------------------------------------------------------------------ #

    def test_survey_correlates_with_true_interest(self):
        """
        A user's survey tags should correlate with their hidden true_interest.

        This is the core quality gate for our synthetic data: if the correlation
        isn't present, the recommendation engine can't be verified against
        ground truth later.

        Method: for each user, check whether any word from their true_interest
        domain appears anywhere in their survey tags. With 70% design alignment
        and realistic noise, we expect at least 50% of users to pass.
        """
        sample = list(User.objects.exclude(true_interest='').select_related('survey'))
        if not sample:
            self.skipTest("No users with true_interest — skipping correlation check")

        correlated = 0

        for user in sample:
            try:
                survey = user.survey
            except SurveyResponse.DoesNotExist:
                continue

            all_tags = survey.goals + survey.skill_gaps + survey.preferred_topics
            tags_text = ' '.join(all_tags).lower()

            # Check for multi-char words from the true_interest phrase
            domain_words = [w for w in user.true_interest.lower().split() if len(w) > 3]
            if any(w in tags_text for w in domain_words):
                correlated += 1

        rate = correlated / len(sample)
        self.assertGreater(
            rate, 0.50,
            f"Expected >50% of surveys to reflect true_interest; got {rate:.0%}. "
            "This suggests the hidden-variable correlation in the generator is broken.",
        )

    def test_interest_domain_usage_correlation(self):
        """
        Users should interact more with courses in their true_interest domain
        than with courses in other domains.

        Verifies that usage events are driven by the hidden interest variable,
        not assigned uniformly at random.
        """
        # Sample active users (those with at least 3 completed events)
        active_user_ids = (
            UsageEvent.objects
            .filter(event_type='completed')
            .values('user_id')
            .annotate(n=Count('event_id'))
            .filter(n__gte=3)
            .values_list('user_id', flat=True)
        )

        if not active_user_ids:
            self.skipTest("Not enough active users to test interest correlation")

        # For each qualifying user, check what fraction of completed courses
        # belong to their true_interest programme area
        in_interest_count = 0
        total_count = 0

        # Build domain -> programme_area mapping for lookup
        domain_to_area = {d: DOMAIN_TO_PROGRAMME[d] for d in TRUE_INTEREST_DOMAINS}

        for user_id in list(active_user_ids)[:50]:  # Cap at 50 to keep test fast
            try:
                user = User.objects.get(user_id=user_id)
            except User.DoesNotExist:
                continue

            interest_area = domain_to_area.get(user.true_interest)
            if not interest_area:
                continue

            completed = UsageEvent.objects.filter(
                user_id=user_id, event_type='completed'
            ).select_related('course')

            for event in completed:
                total_count += 1
                if event.course.programme_area == interest_area:
                    in_interest_count += 1

        if total_count == 0:
            self.skipTest("No completed events found for sampled users")

        in_interest_rate = in_interest_count / total_count
        self.assertGreater(
            in_interest_rate, 0.40,
            f"Expected >40% of completed courses to match user's interest area; "
            f"got {in_interest_rate:.0%}. Hidden-variable may not be driving usage.",
        )
