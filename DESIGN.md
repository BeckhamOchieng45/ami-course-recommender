# AMI Course Recommendation Engine - Design Document

## 1. Scoring Components & Initial Weights

### Three Core Components

1. **Survey Match (weight: 0.35)**
   - Weighted Jaccard overlap between user's `goals + skill_gaps + preferred_topics` and course's `topic + skills_taught`
   - Internal weighting: `goals` (0.5) > `skill_gaps` (0.35) > `preferred_topics` (0.15)
   - Rationale: Stated intent is stronger signal than passive preference

2. **Usage-Based (weight: 0.40)**
   - Content similarity to completed courses with high progress/quiz scores
   - Cohort popularity fallback: "users with your role/industry/seniority who completed X also completed Y"
   - Rationale: 70/20/10 pedagogy emphasizes hands-on application; actual behavior trumps stated preference

3. **Work-Context (weight: 0.25)**
   - Seniority → level relevance mapping (micro-entrepreneur → foundational; executive → leadership)
   - Industry → topic affinity (lightweight heuristic)
   - Rationale: Ensures practical applicability to user's real work environment

### Why These Weights?

- Usage weighted highest (0.40) reflects AMI's action-oriented pedagogy
- Survey second (0.35) captures explicit learner intent
- Work-context third (0.25) provides grounding but shouldn't override explicit user signals
- Total = 1.00 for interpretability

## 2. Cold-Start Strategy

### Continuous Blending Function

```python
usage_confidence = min(1.0, num_completed_events / K)  # K = 5
w_usage_effective = w_usage_base * usage_confidence
w_freed = w_usage_base * (1 - usage_confidence)
w_survey_effective = w_survey_base + w_freed * 0.6
w_context_effective = w_context_base + w_freed * 0.4
```

### Key Properties

- **Smooth transition**: No hard cutover creates score discontinuity
- **K = 5 threshold**: After 5 completed courses, usage signal is fully trusted
- **Freed weight redistribution**: 60% to survey (explicit intent), 40% to work-context (heuristic fallback)
- **Cohort popularity**: Usage scorer's cohort-based component works even at zero personal usage

### Limits

- Pure cold-start (zero survey data) falls back entirely to work-context heuristics + cohort popularity
- Cannot learn from dropped courses (signal is too noisy to interpret intent from abandonment)
- No time-decay on usage events (3-year-old completion weighted same as recent)

## 3. Filtering Approach

### Hard Filters (Exclusions)

1. Already completed courses (`progress_pct >= 95`)
2. Currently in-progress courses (`event_type == 'started'`, no completion)
3. Unmet prerequisites (transitive dependency checking)

### Soft Penalty

**Level mismatch**: -0.2 penalty per level gap (e.g., executive user + beginner course = -0.2)

**Rationale for soft over hard**:
- Strong survey/usage match should outweigh a level mismatch
- Hard filtering causes "entry-level users only see beginner content" bug
- AMI's learners span micro-entrepreneur to executive - rigid level boundaries don't reflect reality

### Fairness Check

- Course price (free vs. paid/certificate) has **zero weight** in scoring
- Consistent with AMI's low-cost-access mission
- Auditable in score breakdown

## 4. Extensibility - Adding New Signals

### Scorer Registry Pattern

```python
# Scoring components register themselves
@register_scorer
def score_manager_assessment(user: User, course: Course) -> ScoreResult:
    """Manager's assessment of employee skill gaps."""
    # Fetch manager assessment data
    # Return (score, weight, reason_fragment)
    pass
```

### Extension Point

- New scorer implements interface: `(user, course) -> (score: float, weight: float, reason: str)`
- Add to `SCORERS` list in `engine/scorers.py`
- No changes to filtering, aggregation, or API layer required
- Weight normalization happens automatically in aggregation step

### What This Enables

- Manager assessment signal (stated interview question)
- Peer recommendation signal ("colleagues like you also took...")
- Temporal signals (trending courses in your industry)
- External signals (LinkedIn skill endorsements, if integrated)

## 5. Implementation Decisions

### Django Models Over Raw JSON

- Schema validation via Django ORM
- Easy admin panel for data inspection
- Migration path to PostgreSQL is trivial (`ENGINE` change only)
- Trade-off: Slight overhead vs. pure JSON files, but worth it for maintainability

### No Real Collaborative Filtering

- User-item matrix too sparse at 1,000 users × 200 courses with realistic engagement rates
- Content similarity + cohort popularity achieves similar effect without cold-start problem
- Saves implementation complexity in a 4-8 hour project

### Templated Reasons Over LLM

- Debuggable: template + data is fully deterministic
- Auditable: AMI reports outcomes to funders; "LLM-generated reason" is not defensible
- Fast: no API latency or token costs
- **Implemented:** Groq (`openai/gpt-oss-120b`) wraps the templated reason in coaching tone as `coaching_reason`. The template always exists as `reason`. LLM enhances tone only — never influences ranking.

### Score Breakdown in API Response

- Not surfaced to end-user UI by default
- Critical for live debugging in interview ("why did this user get this course?")
- Enables A/B testing ("which component is predictive of completion?")

## 6. Assumptions & Design Constraints

1. **Mobile-first**: Keep API payloads lean (JSON response < 10KB typical)
2. **Low connectivity**: No streaming required for core recommendations API; SSE used only for optional AI chat
3. **PostgreSQL in production**: Docker Compose ships Postgres 16 + gunicorn. SQLite used for local dev and all pytest runs.
4. **JWT authentication**: All API endpoints require a Bearer token. Admin superuser created automatically on first run (`admin@email.com` / `password`). Token lifetimes: access 8h, refresh 7d.
5. **English-only**: AMI operates pan-Africa, real system needs i18n
6. **Static catalog**: Courses don't change during recommendation; real system needs cache invalidation
7. **ARM64 / M1-M2 Macs**: Docker images declare `platform: linux/arm64` explicitly. Source dirs bind-mounted individually to prevent macOS venv leaking into container.

## 7. What Would Change at 10k+ Users?

1. **Precompute recommendations**: Nightly batch job writes to `UserRecommendation` table
2. **Cache cohort aggregates**: Redis or materialized view for role/industry/seniority popularity
3. **Approximate NN for content similarity**: FAISS or similar for course tag vectors
4. **Real collaborative filtering**: Matrix factorization becomes viable with denser usage data
5. **Time-decay on usage**: Weight recent behavior > old behavior (half-life function)

What breaks first: **Content-similarity computation per-request**. At 10k users × 200 courses × 5 recs/user, tag-overlap computation becomes bottleneck.
