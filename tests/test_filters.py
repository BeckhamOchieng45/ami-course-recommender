"""
Tests for candidate filtering logic.

Each hard filter is tested in isolation, then the combined get_candidates()
pipeline is verified end-to-end. The fairness invariant (is_paid has no
influence) is tested explicitly.
"""

from django.test import TestCase
from ami_course_recommendations.models import User, Course, UsageEvent
from engine.filters import (
    get_completed_course_ids,
    get_in_progress_course_ids,
    has_unmet_prerequisites,
    get_candidates,
    COMPLETION_THRESHOLD,
)


def make_user(uid: str, **kwargs) -> User:
    defaults = dict(
        role="micro_business_owner",
        industry="retail",
        company_size="micro",
        seniority="micro-entrepreneur",
        stated_goal="test",
        true_interest="cash flow management",
    )
    defaults.update(kwargs)
    return User.objects.create(user_id=uid, **defaults)


def make_course(cid: str, prerequisites=None, is_paid=False, level="foundational") -> Course:
    return Course.objects.create(
        course_id=cid,
        title=f"Course {cid}",
        programme_area="entrepreneurship",
        level=level,
        skills_taught=["cash flow forecasting"],
        duration_mins=60,
        prerequisites=prerequisites or [],
        is_paid=is_paid,
    )


class CompletedCoursesFilterTests(TestCase):
    """Tests for get_completed_course_ids()."""

    def setUp(self):
        self.user = make_user("FLT-USR-001")
        self.course_a = make_course("FLT-CRS-A")
        self.course_b = make_course("FLT-CRS-B")

    def test_completed_course_is_in_set(self):
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_a,
            event_type="completed",
            progress_pct=100.0,
            quiz_score=80.0,
            timestamp="2025-01-01T10:00:00Z",
        )
        ids = get_completed_course_ids(self.user)
        self.assertIn("FLT-CRS-A", ids)

    def test_not_completed_course_not_in_set(self):
        ids = get_completed_course_ids(self.user)
        self.assertNotIn("FLT-CRS-A", ids)

    def test_dropped_event_does_not_count_as_completed(self):
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_a,
            event_type="dropped",
            progress_pct=50.0,
            quiz_score=None,
            timestamp="2025-01-01T10:00:00Z",
        )
        ids = get_completed_course_ids(self.user)
        self.assertNotIn("FLT-CRS-A", ids)

    def test_low_progress_completed_event_excluded(self):
        """
        A 'completed' event with progress below COMPLETION_THRESHOLD should not
        count — guards against systems that emit 'completed' on first view.
        """
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_a,
            event_type="completed",
            progress_pct=COMPLETION_THRESHOLD - 1,
            quiz_score=None,
            timestamp="2025-01-01T10:00:00Z",
        )
        ids = get_completed_course_ids(self.user)
        self.assertNotIn("FLT-CRS-A", ids)

    def test_multiple_courses_tracked(self):
        for course in [self.course_a, self.course_b]:
            UsageEvent.objects.create(
                user=self.user,
                course=course,
                event_type="completed",
                progress_pct=100.0,
                quiz_score=75.0,
                timestamp="2025-01-01T10:00:00Z",
            )
        ids = get_completed_course_ids(self.user)
        self.assertIn("FLT-CRS-A", ids)
        self.assertIn("FLT-CRS-B", ids)


class InProgressFilterTests(TestCase):
    """Tests for get_in_progress_course_ids()."""

    def setUp(self):
        self.user = make_user("FLT-USR-002")
        self.course_a = make_course("FLT-IP-A")
        self.course_b = make_course("FLT-IP-B")

    def test_started_not_completed_is_in_progress(self):
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_a,
            event_type="started",
            progress_pct=40.0,
            quiz_score=None,
            timestamp="2025-01-01T10:00:00Z",
        )
        ids = get_in_progress_course_ids(self.user)
        self.assertIn("FLT-IP-A", ids)

    def test_started_then_completed_is_not_in_progress(self):
        """A course with both started and completed events is done, not in progress."""
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_a,
            event_type="started",
            progress_pct=50.0,
            quiz_score=None,
            timestamp="2025-01-01T09:00:00Z",
        )
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_a,
            event_type="completed",
            progress_pct=100.0,
            quiz_score=80.0,
            timestamp="2025-01-02T10:00:00Z",
        )
        ids = get_in_progress_course_ids(self.user)
        self.assertNotIn("FLT-IP-A", ids)

    def test_untouched_course_not_in_progress(self):
        ids = get_in_progress_course_ids(self.user)
        self.assertNotIn("FLT-IP-B", ids)


class PrerequisiteFilterTests(TestCase):
    """Tests for has_unmet_prerequisites()."""

    def setUp(self):
        self.prereq = make_course("FLT-PRE-001")
        self.dependent = make_course("FLT-PRE-002", prerequisites=["FLT-PRE-001"])
        self.no_prereq = make_course("FLT-PRE-003")

    def test_no_prerequisites_always_passes(self):
        self.assertFalse(has_unmet_prerequisites(self.no_prereq, set()))

    def test_unmet_prerequisite_blocks_course(self):
        completed_ids: set[str] = set()  # Haven't completed anything
        self.assertTrue(has_unmet_prerequisites(self.dependent, completed_ids))

    def test_met_prerequisite_allows_course(self):
        completed_ids = {"FLT-PRE-001"}
        self.assertFalse(has_unmet_prerequisites(self.dependent, completed_ids))

    def test_partial_prerequisites_still_blocks(self):
        """If a course needs A AND B, completing only A should still block."""
        course_two_prereqs = make_course(
            "FLT-PRE-004",
            prerequisites=["FLT-PRE-001", "FLT-PRE-003"],
        )
        # Only completed one of two prerequisites
        completed_ids = {"FLT-PRE-001"}
        self.assertTrue(has_unmet_prerequisites(course_two_prereqs, completed_ids))


class GetCandidatesPipelineTests(TestCase):
    """Integration tests for get_candidates() combining all hard filters."""

    def setUp(self):
        self.user = make_user("FLT-USR-PIPE")
        self.course_fresh = make_course("FLT-PIPE-001")
        self.course_completed = make_course("FLT-PIPE-002")
        self.course_in_progress = make_course("FLT-PIPE-003")
        self.course_prereq_unmet = make_course("FLT-PIPE-004", prerequisites=["FLT-PIPE-002"])
        self.course_prereq_met = make_course("FLT-PIPE-005", prerequisites=["FLT-PIPE-002"])
        self.all_courses = [
            self.course_fresh,
            self.course_completed,
            self.course_in_progress,
            self.course_prereq_unmet,
            self.course_prereq_met,
        ]

        # Mark course_completed as done
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_completed,
            event_type="completed",
            progress_pct=100.0,
            quiz_score=80.0,
            timestamp="2025-01-01T10:00:00Z",
        )
        # Mark course_in_progress as started (not completed)
        UsageEvent.objects.create(
            user=self.user,
            course=self.course_in_progress,
            event_type="started",
            progress_pct=35.0,
            quiz_score=None,
            timestamp="2025-01-05T10:00:00Z",
        )

    def test_completed_course_excluded(self):
        candidates = get_candidates(self.user, self.all_courses)
        ids = [c.course_id for c in candidates]
        self.assertNotIn("FLT-PIPE-002", ids)

    def test_in_progress_course_excluded_by_default(self):
        candidates = get_candidates(self.user, self.all_courses)
        ids = [c.course_id for c in candidates]
        self.assertNotIn("FLT-PIPE-003", ids)

    def test_in_progress_included_when_flag_set(self):
        candidates = get_candidates(
            self.user, self.all_courses, include_in_progress=True
        )
        ids = [c.course_id for c in candidates]
        self.assertIn("FLT-PIPE-003", ids)

    def test_unmet_prerequisite_course_excluded(self):
        """
        FLT-PIPE-004 requires FLT-PIPE-002, which the user completed.
        FLT-PIPE-005 also requires FLT-PIPE-002 — both should pass prerequisite check.
        
        Wait — actually both have the same prereq (FLT-PIPE-002) which IS completed,
        so both should be included. Let's use a truly unmet prereq instead.
        """
        # Create a course that requires something the user hasn't done
        course_blocked = make_course("FLT-PIPE-006", prerequisites=["FLT-PIPE-001"])
        candidates = get_candidates(
            self.user, self.all_courses + [course_blocked]
        )
        ids = [c.course_id for c in candidates]
        # course_fresh has no prerequisite — should be present
        self.assertIn("FLT-PIPE-001", ids)
        # course_blocked requires FLT-PIPE-001 which the user has NOT completed
        self.assertNotIn("FLT-PIPE-006", ids)

    def test_fresh_course_always_included(self):
        candidates = get_candidates(self.user, self.all_courses)
        ids = [c.course_id for c in candidates]
        self.assertIn("FLT-PIPE-001", ids)

    def test_prereq_met_course_included(self):
        """
        FLT-PIPE-005 requires FLT-PIPE-002, which the user completed.
        Should appear in candidates.
        """
        candidates = get_candidates(self.user, self.all_courses)
        ids = [c.course_id for c in candidates]
        self.assertIn("FLT-PIPE-005", ids)


class FairnessInvariantTests(TestCase):
    """
    Verify that is_paid has zero influence on filtering.

    AMI's mission is low-cost access to quality learning. Filtering out paid
    courses would systematically bias recommendations toward free content
    regardless of relevance — inconsistent with that mission.
    """

    def setUp(self):
        self.user = make_user("FLT-FAIR-001")
        self.free_course = make_course("FLT-FAIR-FREE", is_paid=False)
        self.paid_course = make_course("FLT-FAIR-PAID", is_paid=True)
        self.all_courses = [self.free_course, self.paid_course]

    def test_paid_courses_are_not_excluded(self):
        """Paid courses must appear in candidates — price is not a filter criterion."""
        candidates = get_candidates(self.user, self.all_courses)
        ids = [c.course_id for c in candidates]
        self.assertIn(
            "FLT-FAIR-PAID",
            ids,
            "Paid course should not be excluded by get_candidates(). "
            "is_paid must have zero influence on filtering per AMI's low-cost-access mission.",
        )

    def test_free_and_paid_treated_identically(self):
        """A free course and a paid course at the same state should have the same filter outcome."""
        candidates = get_candidates(self.user, self.all_courses)
        ids = [c.course_id for c in candidates]
        self.assertIn("FLT-FAIR-FREE", ids)
        self.assertIn("FLT-FAIR-PAID", ids)
