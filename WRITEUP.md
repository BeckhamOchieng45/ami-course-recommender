# AMI Course Recommendation Engine — Writeup

## 1. Approach and Tradeoffs

### How the engine works

Three scoring components run in parallel for every eligible (user, course) pair. Their outputs are weighted, summed, and sorted:

| Component | Base weight | What it measures |
|---|---|---|
| Survey match | 0.35 | Jaccard overlap between user's stated goals/skill gaps and course skill tags |
| Usage-based | 0.40 | Content similarity to completed courses + cohort popularity |
| Work-context | 0.25 | Seniority–level fit + industry–programme affinity |

**Architecture: pluggable scorer registry.** Each scorer is a function with the signature `(user, course) -> ScoreResult` and registers itself via `@register_scorer`. The aggregation loop iterates over whatever is in the registry — adding a new signal means writing one function and decorating it. Nothing else changes. This was a deliberate upfront design decision to answer "how would you add a manager's assessment signal?" before it was asked.

**Why not collaborative filtering?** With ~1,000 users and ~84 courses, the user-item interaction matrix is extremely sparse. At realistic engagement rates (~3–7 events per active user, ~20% cold-start), there are not enough co-completion pairs to trust matrix factorization — the signal-to-noise ratio is too low and the cold-start problem is immediate. Content similarity on skill tags plus cohort popularity achieves most of the effect of CF without requiring dense interaction data. CF becomes viable and worth adding at 10k+ users with a year of engagement history.

**Where I deliberately kept it simple:**
- No vector embeddings or semantic search — tag overlap is interpretable, debuggable, and accurate enough at this catalog size
- No time-decay on usage events — worth adding at scale, not justified with 18 months of synthetic data
- No real-time recomputation — at 1,000 users, per-request scoring over 84 courses is instant; at 10k+ users this would need to be a nightly batch job
- Templated reasons instead of LLM generation — see section below

---

## 2. Signal Weighting

### Starting weights

```
survey_match:  0.35  (stated intent — what the user says they need)
usage_based:   0.40  (revealed preference — what they actually engage with)
work_context:  0.25  (contextual grounding — what fits their role and industry)
```

Usage is weighted highest because AMI's pedagogy is 70% hands-on application. Actual behavior (completing a course, scoring well on its quiz) is a stronger signal than what someone writes on a survey form — people's stated interests and actual learning priorities don't always match. Survey is second because it captures explicit intent that behavior hasn't had time to reflect yet. Work-context is lowest because it's a heuristic that prevents obviously wrong recommendations but shouldn't override explicit user signals.

### Internal sub-weights within survey match

```
goals field:           0.50
skill_gaps field:      0.35
preferred_topics field: 0.15
```

"I want to improve X" (goal) > "I'm weak at Y" (skill gap) > "I'm interested in Z" (preference). These are ordered by specificity of intent.

### How I'd tune these

The synthetic data has a ground-truth `true_interest` field per user. A concrete tuning loop:
1. Run the engine with current weights across all users
2. Score each recommendation against the user's `true_interest` (does the top-5 include courses in the right domain?)
3. Grid-search or Bayesian-optimize the three base weights to maximize this recovery rate
4. In production, replace `true_interest` with actual downstream outcomes: did the user complete the recommended course? Did they report applying the skill? Those are the real labels.

---

## 3. Cold-Start Strategy

### The mechanism

```python
usage_confidence = min(1.0, num_completed_events / K)  # K = 5
w_usage_effective = W_USAGE_BASE * usage_confidence     # 0.40 * confidence
freed = W_USAGE_BASE * (1.0 - usage_confidence)
w_survey_effective = W_SURVEY_BASE + freed * 0.60       # Survey absorbs 60%
w_context_effective = W_CONTEXT_BASE + freed * 0.40     # Context absorbs 40%
```

At zero completions: usage weight = 0, survey gets 0.35 + 0.24 = 0.59, context gets 0.25 + 0.16 = 0.41. At 5 completions: all scorers carry their base weights.

**Why continuous, not branched:** A hard `if num_events == 0` cutover creates a discontinuity at K — the score jumps on the Kth completion. The linear function is smooth, defensible ("each completion adds 1/5th of the usage signal"), and produces no edge-case bugs at the boundary.

**The cohort bridge:** The usage scorer has two sub-signals: content similarity (zero at cold start) and cohort popularity. Cohort popularity — "other micro-business owners in retail at this stage completed this course" — works at zero personal history. So a cold-start user isn't just falling back to survey + context; they're also getting a weak usage signal via their peer group.

### Limits of this approach

- **No survey, no usage:** If a user completes registration with no survey and no events, they fall entirely to work-context heuristics + cohort popularity. The reason string honestly reflects this: "A strong starting point for micro-entrepreneurs focused on…" rather than pretending to have preference data. The engine fails loudly, not silently.
- **K = 5 is arbitrary:** It's a reasonable default but should be validated against actual engagement data. If most users complete 1–2 courses then churn, K = 5 means most users never exit cold-start mode. Adjust K based on median active-user completion count.
- **No signal from dropped courses:** A user who started and dropped "Cash Flow Forecasting" might mean they found it too hard, or already knew it, or just lost connectivity. The signal is too ambiguous to act on, so dropped events don't increase usage_confidence.

---

## 4. Measuring Success

### Why completion rate is the wrong primary metric

AMI reports that 86% of clients improve business performance after training. That outcome — real behaviour change in the business — is the thing AMI cares about, not course completion. A recommendation engine optimised for completion rate could produce a high-completion list of short, easy courses that people finish but don't apply. That would look good on a dashboard and harm learners.

### The experiment I'd run

**Hypothesis:** Recommendations blended from survey + usage + work-context increase the rate at which learners report applying skills from recommended courses within 30 days, compared to cohort-popularity-only recommendations.

**Metric:** *30-day application rate* — the percentage of recommended-course completers who, on a 30-day follow-up survey, report having applied at least one tool from the course in their business or workplace. This is in the spirit of AMI's existing impact tracking.

**Method:**
- Split new users randomly at registration: 50% receive full-engine recommendations; 50% receive cohort-popularity-only (the simplest defensible baseline)
- Hold for 60 days minimum to allow completions and 30-day follow-ups
- Compare 30-day application rates between arms using a two-proportion z-test
- Minimum detectable effect: 5 percentage points (e.g. 40% → 45%)
- Required sample: ~800 users per arm at 80% power, α=0.05

**Selection bias control:** More-engaged users are more likely to both receive good recommendations (because they have more usage history) and to complete and apply anything. Control by stratifying on baseline engagement level (number of events in first 7 days) before comparing arms. Report results within strata, not just overall.

**What success looks like:** Full-engine arm shows ≥5pp higher 30-day application rate within strata. Not: more completions. Not: higher NPS alone (though that's a useful secondary).

---

## 5. Scaling to 10,000+ Users and a Growing Catalog

### What works fine at current scale and breaks at 10x

| Component | Status at 1k users | Problem at 10k users |
|---|---|---|
| Per-request scoring | Fine (84 courses × <100ms) | 840–2,000 courses per request, blocking |
| Cohort popularity query | Fine (single COUNT query) | N+1 query pattern per candidate course |
| Tag overlap computation | Fine (small sets) | O(users × courses) becomes expensive |
| SQLite | Fine | Concurrent writes under load; switch to PostgreSQL |

### What I'd change first

**Precompute recommendations nightly.** A `UserRecommendation` table stores the top-20 precomputed recs per user. The API becomes a simple `SELECT` — no scoring at request time. Staleness of up to 24 hours is acceptable for a learning platform; real-time personalisation adds complexity without meaningful benefit at this frequency of catalog change.

```sql
CREATE TABLE user_recommendations (
    user_id VARCHAR, course_id VARCHAR, position INT,
    score FLOAT, reason TEXT, computed_at TIMESTAMP,
    PRIMARY KEY (user_id, position)
);
```

**Cache cohort aggregates.** Cohort popularity (completed counts by role/industry/seniority) is cheap to compute once and expensive to recompute per request at scale. A nightly materialized view or Redis hash keyed on `(role, industry, seniority, course_id)` reduces the cohort query from N per-user DB hits to a single cache lookup.

**Approximate nearest-neighbor for content similarity.** As the catalog grows past ~500 courses, pairwise tag-overlap computation becomes the bottleneck. Index course tag vectors in FAISS or a vector-capable database (pgvector). This also opens the door to richer semantic matching — embedding course descriptions with a small model gives better overlap detection than exact string matching on tags.

**Real collaborative filtering.** At 10k users with a year of engagement, the interaction matrix becomes dense enough to support matrix factorization (ALS or SVD). Add it as a fourth scorer in the registry; start its weight at 0.10 and tune upward as the model proves itself against the 30-day application metric above.

**Switch to PostgreSQL.** The Django ORM change is `ENGINE = 'django.db.backends.postgresql'`. The model layer doesn't change. Worth doing before scale for concurrent writes, proper indexing on JSONB fields, and `ArrayField` support.

**AMI-specific constraint: mobile-first, low-bandwidth.** Keep API responses under 10KB (the current N=5 response is ~3KB). If the catalog grows significantly, consider returning only `course_id + title + reason` in the list endpoint and letting the client fetch full course detail on tap — a separate `GET /courses/{course_id}` call that's easily cacheable.

---

## 6. On LLMs — What's Implemented and Where the Boundary Is

### What Groq does in this system

**`coaching_reason` enhancement.** Every recommendation carries two reason strings. `reason` is the deterministic template — "Because you told us you want to improve cash flow forecasting, we suggest Cash Flow Forecasting for Small Businesses." `coaching_reason` is that same content re-voiced by Groq (`openai/gpt-oss-120b`) in AMI's coaching tone — warmer, more personal, connected to the learner's stated goal and context. When `GROQ_API_KEY` is set, every recommendation's `coaching_reason` is Groq-enhanced. When absent, `coaching_reason` silently equals `reason` — no errors, no broken responses.

**`/api/chat` streaming coaching conversation.** A `POST /api/chat` endpoint streams a live coaching conversation via SSE. The system prompt embeds the learner's full profile (role, industry, seniority, stated goal, signal mode), the recommended course, and the score breakdown. The coach can explain exactly why this course was surfaced, what the learner will get from it, and what to do next — grounded in real data, not generic LLM output. Responses stream token-by-token and render as formatted markdown in the UI.

Both features degrade gracefully: `GROQ_API_KEY` absent → `coaching_reason` equals `reason`, `/api/chat` returns a clear message explaining the key is missing.

### Why the LLM stays out of ranking

AMI reports verified outcome data — 86% business-performance improvement — to funders and partners. A recommendation engine that silently changes its rankings because an LLM's weights drifted, or because a new model version interprets "cash flow" differently, is not defensible in that context. The scoring logic must be deterministic, versioned, and auditable.

The current architecture enforces this boundary explicitly:
- `engine/scorers.py`, `engine/coldstart.py`, `engine/filters.py` — zero LLM imports
- `engine/llm.py` — presentation layer only; called from `explainer.py` after the ranking is already final
- `engine/explainer.py` — builds the templated `reason` first, then optionally enhances tone via Groq

The right mental model: the engine decides *which* course to recommend. Groq decides *how to phrase* that recommendation. Those two concerns are separated by a clear module boundary and never cross.

### What an LLM could add next

**Semantic matching on free-text survey responses.** Right now learners select from structured tags. If they wrote "I'm struggling to make payroll at the end of the month" in a free-text field, an embedding model could map that to `cash flow management` far better than keyword matching. This would improve survey scorer recall without changing the weighting logic — the LLM output becomes just another source of tags feeding into the existing Jaccard scorer.

---

## 7. What's Deployed

Beyond the core recommendation engine, the system ships with:

**Authentication** — `djangorestframework-simplejwt` JWT auth on all endpoints. Access tokens expire in 8 hours, refresh tokens in 7 days. A `jwt_required` decorator was added to the existing plain Django views rather than rewriting them as DRF APIViews — a surgical change that kept the diff small and the scoring logic untouched.

**Admin dashboard** — A single-page UI at `/` shows all 1,000 learners in a sidebar with human-readable display names ("Manager #42", "Entrepreneur #7"), signal-mode badges (cold-start / blended / behavioral), search, and filters. Clicking a learner loads their ranked recommendations. Each card has a "Why?" panel showing the exact score breakdown, cold-start formula with live numbers, and course details. An "Ask coach" button opens the streaming Groq chat.

**Superuser auto-creation** — `admin@email.com` / `password` is created on first run (both locally via `datagen/generate.py` and in Docker via `entrypoint.sh`). These credentials are pre-filled on the login page for demo purposes and must be changed before any non-local deployment.

**Docker + Postgres** — `docker-compose up --build` starts Postgres 16 and the Django/gunicorn web service. `entrypoint.sh` waits for Postgres readiness (pure Python socket check, no `netcat` dependency), runs migrations, seeds data if the DB is empty, creates the superuser, and starts gunicorn. Both services declare `platform: linux/arm64` for M1/M2 Mac compatibility. Source directories are bind-mounted individually rather than the whole project root — this prevents the macOS venv from overwriting the container's linux/arm64 venv, which was the root cause of the `gunicorn: cannot execute` error on Apple Silicon.
