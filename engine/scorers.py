"""
Pluggable scorer architecture for course recommendations.

Design:
- Each scorer implements a simple interface: (user, course) -> ScoreResult
- ScoreResult carries score (0-1), weight (configurable), and reason fragment
- Scorers register themselves via decorator pattern for extensibility
- Final recommendation = weighted sum of all registered scorers

This makes "add a new signal" trivial (stated interview question).
"""

from dataclasses import dataclass
from typing import Protocol, Callable
from ami_course_recommendations.models import User, Course


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreResult:
    """
    Output of a single scoring component.
    
    Attributes:
        score: Raw score 0.0-1.0 (higher = better match)
        weight: Relative importance of this component (used in aggregation)
        reason_fragment: Human-readable explanation snippet (used if this
                        component is the highest contributor)
    """
    score: float
    weight: float
    reason_fragment: str


class ScorerFunction(Protocol):
    """Type signature for a scorer: (user, course) -> ScoreResult."""
    def __call__(self, user: User, course: Course) -> ScoreResult: ...


# ---------------------------------------------------------------------------
# Scorer registry
# ---------------------------------------------------------------------------

_SCORERS: list[ScorerFunction] = []

 
def register_scorer(func: ScorerFunction) -> ScorerFunction:
    """
    Decorator to register a scorer function.
    
    Usage:
        @register_scorer
        def score_my_signal(user: User, course: Course) -> ScoreResult:
            ...
    """
    _SCORERS.append(func)
    return func


def get_all_scorers() -> list[ScorerFunction]:
    """Return all registered scorers in registration order."""
    return _SCORERS.copy()


# ---------------------------------------------------------------------------
# Component 1: Survey Match
# ---------------------------------------------------------------------------

# Survey component weights: goals and skill_gaps are stronger signals than
# passive preferred_topics
SURVEY_GOAL_WEIGHT = 0.50
SURVEY_SKILLGAP_WEIGHT = 0.35
SURVEY_PREFERRED_WEIGHT = 0.15

# Base weight for survey scorer in overall aggregation (from DESIGN.md)
SURVEY_BASE_WEIGHT = 0.35


@register_scorer
def score_survey_match(user: User, course: Course) -> ScoreResult:
    """
    Survey-based content match using weighted Jaccard overlap.
    
    Computes overlap between user's stated goals/skill_gaps/preferred_topics
    and the course's skills_taught tags. Goals and skill_gaps are weighted
    higher than preferred_topics (stated intent > passive preference).
    
    Design rationale:
    - Jaccard (not cosine) because tag sets are small (3-8 tags) and unweighted,
      so intersection/union is more interpretable than vector similarity
    - Multi-field weighting reflects that "I want to learn X" (goal) is a
      stronger signal than "I'm interested in X" (preference)
    """
    try:
        survey = user.survey
    except Exception:
        # User has no survey data — return zero score
        return ScoreResult(
            score=0.0,
            weight=SURVEY_BASE_WEIGHT,
            reason_fragment="(no survey data available)",
        )
    
    # Combine survey fields with internal weighting
    user_tags_weighted: list[tuple[str, float]] = []
    
    for tag in survey.goals:
        user_tags_weighted.append((tag.lower(), SURVEY_GOAL_WEIGHT))
    for tag in survey.skill_gaps:
        user_tags_weighted.append((tag.lower(), SURVEY_SKILLGAP_WEIGHT))
    for tag in survey.preferred_topics:
        user_tags_weighted.append((tag.lower(), SURVEY_PREFERRED_WEIGHT))
    
    if not user_tags_weighted:
        return ScoreResult(
            score=0.0,
            weight=SURVEY_BASE_WEIGHT,
            reason_fragment="(no survey tags provided)",
        )
    
    course_tags = set(skill.lower() for skill in course.skills_taught)
    
    if not course_tags:
        return ScoreResult(
            score=0.0,
            weight=SURVEY_BASE_WEIGHT,
            reason_fragment="",
        )
    
    # Weighted Jaccard: intersection weight / union weight
    intersection_weight = 0.0
    matched_tags: list[str] = []
    
    for user_tag, tag_weight in user_tags_weighted:
        if user_tag in course_tags:
            intersection_weight += tag_weight
            matched_tags.append(user_tag)
    
    # Union weight = sum of all user tag weights + count of unmatched course tags
    union_weight = sum(w for _, w in user_tags_weighted)
    unmatched_course_tags = course_tags - set(tag for tag, _ in user_tags_weighted)
    union_weight += len(unmatched_course_tags)  # Course tags have implicit weight 1.0
    
    if union_weight == 0:
        score = 0.0
    else:
        score = intersection_weight / union_weight
    
    # Build reason fragment highlighting the strongest match
    reason = ""
    if matched_tags:
        # Find which survey field contributed the best match
        goal_matches = [t for t in matched_tags if t in [g.lower() for g in survey.goals]]
        gap_matches = [t for t in matched_tags if t in [g.lower() for g in survey.skill_gaps]]
        
        if goal_matches:
            reason = f"matches your goal of learning {goal_matches[0]}"
        elif gap_matches:
            reason = f"addresses your skill gap in {gap_matches[0]}"
        else:
            reason = f"aligns with your interest in {matched_tags[0]}"
    
    return ScoreResult(
        score=score,
        weight=SURVEY_BASE_WEIGHT,
        reason_fragment=reason,
    )



# ---------------------------------------------------------------------------
# Component 2: Usage-Based Scoring
# ---------------------------------------------------------------------------

# Base weight for usage scorer in overall aggregation
USAGE_BASE_WEIGHT = 0.40


@register_scorer
def score_usage_based(user: User, course: Course) -> ScoreResult:
    """
    Usage-based content similarity + cohort popularity.
    
    Two sub-signals:
    1. Content similarity to courses the user completed with high progress/quiz
    2. Cohort popularity: "users with your role/industry/seniority who completed
       X also completed Y"
    
    Design rationale:
    - Reflects AMI's 70/20/10 pedagogy: actual behavior (completion + quiz score)
      is the strongest signal
    - Content similarity uses simple tag overlap (not collaborative filtering)
      because the user-item matrix is too sparse at 1,000 users
    - Cohort popularity doubles as the cold-start bridge: works even at zero
      personal usage history
    """
    from django.db.models import Q, Avg, Count
    from ami_course_recommendations.models import UsageEvent
    
    # Get user's completed courses with high engagement (progress >= 80, quiz >= 60)
    completed_events = UsageEvent.objects.filter(
        user=user,
        event_type='completed',
        progress_pct__gte=80,
    ).select_related('course')
    
    completed_courses = [e.course for e in completed_events if e.quiz_score and e.quiz_score >= 60]
    
    # Sub-score 1: Content similarity to completed courses
    content_score = 0.0
    similar_course_title = ""
    
    if completed_courses:
        # Compute tag overlap with each completed course
        course_tags = set(skill.lower() for skill in course.skills_taught)
        
        best_overlap = 0.0
        best_match_course = None
        
        for completed_course in completed_courses:
            completed_tags = set(skill.lower() for skill in completed_course.skills_taught)
            
            if not completed_tags or not course_tags:
                continue
            
            intersection = course_tags & completed_tags
            union = course_tags | completed_tags
            
            if union:
                jaccard = len(intersection) / len(union)
                if jaccard > best_overlap:
                    best_overlap = jaccard
                    best_match_course = completed_course
        
        content_score = best_overlap
        if best_match_course:
            similar_course_title = best_match_course.title
    
    # Sub-score 2: Cohort popularity
    # Find users with same role, industry, and seniority who completed this course
    cohort_users = User.objects.filter(
        role=user.role,
        industry=user.industry,
        seniority=user.seniority,
    ).exclude(user_id=user.user_id)
    
    if cohort_users.exists():
        cohort_user_ids = list(cohort_users.values_list('user_id', flat=True))
        
        # Count how many cohort users completed this course with high engagement
        cohort_completions = UsageEvent.objects.filter(
            user_id__in=cohort_user_ids,
            course=course,
            event_type='completed',
            progress_pct__gte=80,
        ).count()
        
        # Normalize by cohort size (cap at 20% to avoid over-weighting very popular courses)
        cohort_popularity = min(0.20, cohort_completions / len(cohort_user_ids))
    else:
        cohort_popularity = 0.0
    
    # Combine: 70% content similarity, 30% cohort popularity
    # (Content similarity is zero for cold-start users, so cohort carries the signal)
    final_score = (0.70 * content_score) + (0.30 * cohort_popularity)
    
    # Build reason
    reason = ""
    if content_score > 0.3 and similar_course_title:
        reason = f"builds on your completion of '{similar_course_title}'"
    elif cohort_popularity > 0.05:
        reason = f"popular with similar {user.role}s in {user.industry}"
    
    return ScoreResult(
        score=final_score,
        weight=USAGE_BASE_WEIGHT,
        reason_fragment=reason,
    )


# ---------------------------------------------------------------------------
# Component 3: Work-Context Scoring
# ---------------------------------------------------------------------------

# Base weight for work-context scorer in overall aggregation
CONTEXT_BASE_WEIGHT = 0.25

# Seniority -> preferred course levels
SENIORITY_LEVEL_PREFERENCES = {
    'micro-entrepreneur': ['foundational', 'intermediate'],
    'sme-manager': ['intermediate', 'advanced'],
    'early-career': ['foundational', 'intermediate'],
    'senior-leader': ['intermediate', 'advanced'],
}

# Industry -> programme area affinity (lightweight heuristic)
INDUSTRY_PROGRAMME_AFFINITY = {
    'retail': ['entrepreneurship', 'workplace'],
    'agriculture': ['entrepreneurship', 'workplace'],
    'financial_services': ['entrepreneurship', 'leadership'],
    'manufacturing': ['entrepreneurship', 'leadership'],
    'professional_services': ['leadership', 'workplace'],
    'ngo_development': ['leadership', 'womens_leadership'],
    'technology': ['ai_strategy', 'workplace', 'leadership'],
    'hospitality': ['entrepreneurship', 'workplace'],
}


@register_scorer
def score_work_context(user: User, course: Course) -> ScoreResult:
    """
    Work-context relevance: seniority → level fit, industry → programme area affinity.
    
    Two sub-signals:
    1. Seniority-level alignment: micro-entrepreneurs prefer foundational content;
       senior executives prefer advanced leadership modules
    2. Industry-programme affinity: tech workers have higher affinity for AI strategy;
       NGO leaders for women's leadership, etc.
    
    Design rationale:
    - Ensures practical applicability to user's real work environment
    - Provides grounding when survey and usage signals are weak
    - Lightweight heuristics (not ML) because the feature space is small and interpretable
    """
    # Sub-score 1: Seniority-level fit
    preferred_levels = SENIORITY_LEVEL_PREFERENCES.get(user.seniority, [])
    
    if course.level in preferred_levels:
        level_score = 1.0
    else:
        # Soft penalty for level mismatch (not a hard filter)
        level_score = 0.3
    
    # Sub-score 2: Industry-programme affinity
    preferred_programmes = INDUSTRY_PROGRAMME_AFFINITY.get(user.industry, [])
    
    if course.programme_area in preferred_programmes:
        industry_score = 1.0
    else:
        # Partial credit for any programme area (no hard filtering)
        industry_score = 0.4
    
    # Combine: 60% level fit, 40% industry fit
    final_score = (0.60 * level_score) + (0.40 * industry_score)
    
    # Build reason
    reason = ""
    if level_score == 1.0 and industry_score == 1.0:
        reason = f"well-suited for {user.seniority}s in {user.industry}"
    elif level_score == 1.0:
        reason = f"appropriate level for {user.seniority}"
    elif industry_score == 1.0:
        reason = f"relevant to {user.industry} professionals"
    
    return ScoreResult(
        score=final_score,
        weight=CONTEXT_BASE_WEIGHT,
        reason_fragment=reason,
    )
