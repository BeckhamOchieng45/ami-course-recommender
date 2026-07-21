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

