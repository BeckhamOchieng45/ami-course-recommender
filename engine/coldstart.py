"""
Cold-start blending and score aggregation.

The central design decision here is that the transition from cold-start to
behavior-driven recommendations is a *continuous function*, not a branch.

  usage_confidence = min(1.0, num_completed_events / K)

At zero completions, usage_confidence = 0 and the full 0.40 base weight is
redistributed to survey (60%) and work-context (40%). As the user accumulates
completed courses, usage confidence grows linearly until K completions, at which
point the full 0.40 weight is active and nothing extra flows to the other scorers.

Why continuous rather than a hard if-new-user/else branch:
- A hard cutover at K produces a visible score discontinuity right at the boundary
- The threshold itself is arbitrary and hard to defend
- A smooth function is easier to reason about and debug
"""

from dataclasses import dataclass
from ami_course_recommendations.models import User, Course, UsageEvent
from engine.scorers import ScoreResult, get_all_scorers, score_usage_based, score_survey_match, score_work_context

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of completed courses after which usage_confidence = 1.0
# (i.e., usage signal is fully trusted). Chosen to be low enough that
# a new user transitions quickly, but large enough to filter noise.
K_COLD_START: int = 5

# Base weights per DESIGN.md — must sum to 1.0
W_USAGE_BASE: float = 0.40
W_SURVEY_BASE: float = 0.35
W_CONTEXT_BASE: float = 0.25

# Freed-weight redistribution split: survey absorbs 60%, work-context 40%
FREED_TO_SURVEY: float = 0.60
FREED_TO_CONTEXT: float = 0.40


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComponentBreakdown:
    """
    Per-component contribution to the final score.
    Surfaced in API responses to enable live debugging and A/B analysis.
    """
    name: str
    raw_score: float       # Scorer's raw output (0–1)
    effective_weight: float  # Weight after cold-start adjustment
    contribution: float    # raw_score * effective_weight


@dataclass(frozen=True)
class AggregatedScore:
    """
    Final recommendation score for a single (user, course) pair.
    """
    course: Course
    final_score: float
    usage_confidence: float        # 0.0 = pure cold-start, 1.0 = fully behavior-driven
    breakdown: list[ComponentBreakdown]
    primary_reason: str            # Reason from the highest-contributing component


# ---------------------------------------------------------------------------
# Cold-start confidence
# ---------------------------------------------------------------------------

def compute_usage_confidence(user: User) -> float:
    """
    Return a value in [0, 1] representing how much personal usage history
    this user has, normalised by K_COLD_START.

    At 0 completed courses  → 0.0 (pure cold-start, use survey + work-context)
    At K completed courses  → 1.0 (fully behavior-driven)
    Between 0 and K         → linear interpolation

    Only *completed* events count — dropped/started events are too noisy
    to be treated as positive signal about what the user finds valuable.
    """
    num_completed = UsageEvent.objects.filter(
        user=user,
        event_type='completed',
    ).count()

    return min(1.0, num_completed / K_COLD_START)


def compute_effective_weights(usage_confidence: float) -> tuple[float, float, float]:
    """
    Return (w_usage, w_survey, w_context) after cold-start adjustment.

    As usage_confidence rises from 0 → 1, weight flows *from* survey and
    work-context *into* usage. At cold-start (confidence=0), usage gets
    zero weight and its full 0.40 share is redistributed. At full confidence,
    all three scorers carry their base weights.

    Returns:
        Tuple of (w_usage_effective, w_survey_effective, w_context_effective)
        guaranteed to sum to 1.0.
    """
    w_usage = W_USAGE_BASE * usage_confidence

    freed = W_USAGE_BASE * (1.0 - usage_confidence)
    w_survey = W_SURVEY_BASE + (freed * FREED_TO_SURVEY)
    w_context = W_CONTEXT_BASE + (freed * FREED_TO_CONTEXT)

    return w_usage, w_survey, w_context


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------

def aggregate_scores(user: User, course: Course) -> AggregatedScore:
    """
    Compute the final aggregated recommendation score for a (user, course) pair.

    Steps:
    1. Compute usage_confidence from completed event count
    2. Derive effective weights via cold-start blending
    3. Call each registered scorer
    4. Map each scorer's raw output to its effective weight (overriding the
       base weight embedded in the ScoreResult)
    5. Sum contributions, select primary reason from highest contributor

    The per-component breakdown is preserved so the API can expose it
    for debugging and A/B analysis without adding latency.
    """
    usage_confidence = compute_usage_confidence(user)
    w_usage, w_survey, w_context = compute_effective_weights(usage_confidence)

    # Map scorer function to its effective weight after blending
    # This is the one place where cold-start adjustment overrides the
    # base weights each scorer declares internally.
    effective_weight_map = {
        score_survey_match: w_survey,
        score_usage_based: w_usage,
        score_work_context: w_context,
    }

    breakdowns: list[ComponentBreakdown] = []
    final_score = 0.0

    for scorer in get_all_scorers():
        result: ScoreResult = scorer(user, course)
        eff_weight = effective_weight_map.get(scorer, result.weight)
        contribution = result.score * eff_weight
        final_score += contribution
        breakdowns.append(ComponentBreakdown(
            name=scorer.__name__,
            raw_score=result.score,
            effective_weight=eff_weight,
            contribution=contribution,
        ))

    # Primary reason: from the highest-contributing component that has a reason
    best_breakdown = max(
        (b for b in breakdowns if b.contribution > 0),
        key=lambda b: b.contribution,
        default=None,
    )

    # Re-run the best scorer to get its reason_fragment
    primary_reason = _build_primary_reason(user, course, best_breakdown, usage_confidence)

    return AggregatedScore(
        course=course,
        final_score=round(final_score, 6),
        usage_confidence=round(usage_confidence, 4),
        breakdown=breakdowns,
        primary_reason=primary_reason,
    )


def _build_primary_reason(
    user: User,
    course: Course,
    best_breakdown: ComponentBreakdown | None,
    usage_confidence: float,
) -> str:
    """
    Re-derive the reason string from the highest-contributing scorer.

    Kept separate from aggregate_scores() so that reason generation can be
    extended or replaced without touching the aggregation logic.
    """
    if best_breakdown is None:
        return f"Popular with similar {user.role}s in {user.industry}"

    scorer_map = {
        'score_survey_match': score_survey_match,
        'score_usage_based': score_usage_based,
        'score_work_context': score_work_context,
    }

    scorer_fn = scorer_map.get(best_breakdown.name)
    if scorer_fn is None:
        return f"Recommended based on your profile"

    result: ScoreResult = scorer_fn(user, course)

    if result.reason_fragment:
        return result.reason_fragment

    # Fallback: use cold-start awareness to produce a generic but honest reason
    if usage_confidence < 0.2:
        return f"Popular with similar {user.role}s in {user.industry}"

    return f"Matches your learning profile"


# ---------------------------------------------------------------------------
# Batch ranking: produce top-N recommendations for a user
# ---------------------------------------------------------------------------

def rank_courses(
    user: User,
    candidates: list[Course],
) -> list[AggregatedScore]:
    """
    Score all candidate courses for a user and return them sorted
    descending by final_score.

    Candidates should already have hard filters applied (see engine/filters.py).
    This function is pure scoring — it does not filter.
    """
    scored = [aggregate_scores(user, course) for course in candidates]
    return sorted(scored, key=lambda s: s.final_score, reverse=True)
