"""
Candidate filtering for course recommendations.

Filters run BEFORE scoring so the scorer never wastes cycles on ineligible
courses. Two categories:

Hard filters (exclusion):
  1. Already completed — user has a completed event with progress >= 95%
  2. In-progress — user has a started/incomplete event (configurable)
  3. Unmet prerequisites — user hasn't completed a required prerequisite course

Soft adjustment (handled in scoring, not here):
  - Level mismatch — applies a score penalty in score_work_context(), not here.
    Kept as a penalty rather than a filter because a strong survey/usage signal
    should be able to surface an advanced course for a motivated foundational
    learner. Hard-filtering here is the root cause of 'entry-level users only
    ever see beginner content regardless of stated goals.'

Fairness invariant:
  - course.is_paid has zero influence here and zero weight in any scorer.
    Free vs. paid/certificate courses are treated identically. This is an
    explicit choice consistent with AMI's low-cost-access mission, and worth
    being able to state in a review.
"""

from ami_course_recommendations.models import User, Course, UsageEvent

# Progress threshold above which a course is considered "completed"
COMPLETION_THRESHOLD: float = 95.0


def get_completed_course_ids(user: User) -> set[str]:
    """
    Return the set of course_ids the user has completed.

    Completed = event_type 'completed' with progress_pct >= COMPLETION_THRESHOLD.
    Using a threshold rather than event_type alone because some systems emit
    a 'completed' event on first watch-through with low progress — being
    conservative here avoids permanently hiding courses the user only skimmed.
    """
    events = UsageEvent.objects.filter(
        user=user,
        event_type='completed',
        progress_pct__gte=COMPLETION_THRESHOLD,
    ).values_list('course_id', flat=True)

    return set(events)


def get_in_progress_course_ids(user: User) -> set[str]:
    """
    Return the set of course_ids the user has started but not completed.

    Default behaviour is to exclude these from recommendations — recommending
    a course already in progress is noise for the learner. Set include_in_progress
    to True in get_candidates() to override (e.g. for a 'continue learning' panel).
    """
    started_ids = set(
        UsageEvent.objects.filter(
            user=user,
            event_type='started',
        ).values_list('course_id', flat=True)
    )

    completed_ids = get_completed_course_ids(user)

    # In-progress = started but NOT completed
    return started_ids - completed_ids


def get_completed_course_ids_for_prereqs(user: User) -> set[str]:
    """
    Return all course_ids the user has ANY completed event for, used
    specifically for prerequisite checking.

    Slightly more permissive than get_completed_course_ids() — we don't
    require the strict progress threshold here because a user who completed
    a prerequisite at 80% has still demonstrated sufficient knowledge.
    """
    return set(
        UsageEvent.objects.filter(
            user=user,
            event_type='completed',
        ).values_list('course_id', flat=True)
    )


def has_unmet_prerequisites(course: Course, completed_ids: set[str]) -> bool:
    """
    Return True if the course has any prerequisite the user hasn't completed.

    Transitive chains (A → B → C) are handled because each course's
    prerequisites list only its immediate predecessors; the caller passes
    the full set of completed course_ids, so transitive completion is
    implicit.
    """
    if not course.prerequisites:
        return False

    for prereq_id in course.prerequisites:
        if prereq_id not in completed_ids:
            return True

    return False


def get_candidates(
    user: User,
    all_courses: list[Course] | None = None,
    include_in_progress: bool = False,
) -> list[Course]:
    """
    Return the list of courses eligible for recommendation for this user.

    Applies all hard filters in order:
      1. Exclude already-completed courses
      2. Exclude in-progress courses (unless include_in_progress=True)
      3. Exclude courses with unmet prerequisites

    Note on is_paid:
      Not filtered here. Free and paid/certificate courses are treated
      identically — excluding paid courses would bias recommendations
      toward free content regardless of quality or relevance, which
      contradicts AMI's mission of practical, outcome-focused learning.

    Args:
        user: The learner to generate candidates for.
        all_courses: Course queryset/list to filter from. If None, uses all
                     courses in the database.
        include_in_progress: If True, courses already started are not excluded.

    Returns:
        List of Course objects eligible for scoring.
    """
    if all_courses is None:
        all_courses = list(Course.objects.all())

    completed_ids = get_completed_course_ids(user)
    prereq_completed_ids = get_completed_course_ids_for_prereqs(user)
    in_progress_ids = get_in_progress_course_ids(user) if not include_in_progress else set()

    candidates = []
    for course in all_courses:
        # Hard filter 1: already completed
        if course.course_id in completed_ids:
            continue

        # Hard filter 2: in-progress
        if course.course_id in in_progress_ids:
            continue

        # Hard filter 3: unmet prerequisites
        if has_unmet_prerequisites(course, prereq_completed_ids):
            continue

        candidates.append(course)

    return candidates
