# AMI Course Recommendation Engine

Intelligent course recommendation service for the AMI AI Coach Bot. Given a learner, returns the top-N recommended courses with ranked position, confidence score, and a human-readable reason the coach can surface directly to the participant.

> "Because you told us you want to improve cash flow management and completed Intro to Bookkeeping, we suggest Cash Flow Forecasting for Small Businesses."

---

## Quick Start

### 1. Install

```bash
# Requires Python 3.13+ and uv
git clone <repo-url>
cd AMI

cp .env.example .env          # Add ANTHROPIC_API_KEY if using the LLM bonus feature
uv sync
```

### 2. Set up the database and generate synthetic data

```bash
uv run python manage.py migrate
uv run python datagen/generate.py
```

This creates **84 courses**, **1,000 users**, **1,000 survey responses**, and ~**3,900 usage events** in `db.sqlite3`.

### 3. Run the server

```bash
uv run python manage.py runserver
```

Server starts at `http://127.0.0.1:8000`.

---

## API

### `GET /api/users/{user_id}/recommendations`

Returns top-N recommended courses for a user.

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `n` | integer | `5` | Number of recommendations (1–20) |

**Example request**

```bash
curl "http://127.0.0.1:8000/api/users/USR-00001/recommendations?n=3"
```

**Example response**

```json
{
  "user_id": "USR-00001",
  "usage_confidence": 1.0,
  "recommendation_count": 3,
  "recommendations": [
    {
      "position": 1,
      "course": {
        "course_id": "CRS-LDR-009",
        "title": "KPI Design for Non-Finance Managers",
        "programme_area": "leadership",
        "level": "advanced",
        "duration_mins": 164,
        "is_paid": false,
        "skills_taught": ["feedback delivery", "KPI tracking", "performance reviews", "goal-setting frameworks", "coaching conversations"]
      },
      "score": 0.761596,
      "usage_confidence": 1.0,
      "reason": "Because you told us you want to improve coaching conversations, we suggest \"KPI Design for Non-Finance Managers\".",
      "reason_detail": "Your survey identified coaching conversations as a priority. \"KPI Design for Non-Finance Managers\" covers exactly this — it's a practical, hands-on module you can apply directly to set clear performance targets.",
      "reason_driver": "survey",
      "score_breakdown": [
        {"component": "survey_match", "raw_score": 0.8246, "effective_weight": 0.35, "contribution": 0.2886},
        {"component": "usage_based",  "raw_score": 0.7075, "effective_weight": 0.40, "contribution": 0.2830},
        {"component": "work_context", "raw_score": 0.7600, "effective_weight": 0.25, "contribution": 0.1900}
      ]
    }
  ]
}
```

**Error responses**

| Status | Condition |
|---|---|
| `404` | Unknown `user_id` |
| `400` | `n` is not an integer, or outside range 1–20 |

---

## UI

Open `http://127.0.0.1:8000/` in a browser, or navigate directly to `http://127.0.0.1:8000/ui/index.html`.

The single-page UI lets you enter any user ID, select the number of recommendations, and view ranked results with score breakdowns. Kept deliberately minimal (vanilla JS, zero build step) — the brief prioritises recommendation quality over frontend polish.

---

## Run Tests

```bash
uv run pytest
```

116 tests across data generation, scoring, filtering, cold-start blending, explainability, and API. All pass in under 3 seconds.

---

## Project Structure

```
AMI/
├── ami_course_recommendations/   # Django app: models, views, URLs
│   ├── models.py                 # Course, User, UsageEvent, SurveyResponse
│   └── views.py                  # RecommendationsView (the API)
├── engine/                       # Pure scoring logic (no Django dependencies)
│   ├── scorers.py                # Pluggable scorer registry + 3 components
│   ├── coldstart.py              # Weight blending + score aggregation
│   ├── filters.py                # Hard filters + fairness invariant
│   └── explainer.py              # Reason string generation
├── datagen/
│   └── generate.py               # Synthetic data generator (1,000 users)
├── tests/                        # 116 tests, co-located by feature
├── sample_outputs/               # Real API output for 3 representative users
├── ui/index.html                 # Minimal single-page UI (bonus)
├── WRITEUP.md                    # Approach, tradeoffs, experiment design
└── DESIGN.md                     # Pre-implementation design decisions
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | No | Only needed for the optional LLM coaching-tone wrapper. See `WRITEUP.md` §6. |

Never hardcode API keys. Read from `.env` (excluded from git via `.gitignore`).

---

## How It Works

Three scoring components run for every eligible (user, course) pair:

| Component | Base weight | Signal |
|---|---|---|
| Survey match | 0.35 | Weighted Jaccard overlap: user's goals/skill-gaps ↔ course skill tags |
| Usage-based | 0.40 | Content similarity to completed courses + cohort popularity |
| Work-context | 0.25 | Seniority–level fit + industry–programme affinity |

**Cold-start:** New users with no usage history have the usage weight redistributed to survey (60%) and work-context (40%), ensuring sensible recommendations from day one. The transition is continuous — `usage_confidence = min(1, completed_courses / 5)` — not a hard branch.

**Filtering:** Completed courses, in-progress courses, and courses with unmet prerequisites are excluded before scoring. Free vs. paid courses are treated identically (AMI's low-cost-access mission).

**Explainability:** Every recommendation carries a specific reason tied to which signal contributed most — not a generic string.

See `WRITEUP.md` for the full design rationale, signal weighting, cold-start strategy, experiment design, and scaling plan.

---

## Sample Outputs

Three representative users are documented in `sample_outputs/`:

| File | Scenario |
|---|---|
| `cold_start_user.json` | USR-00839 — zero usage history, survey-only |
| `in_between_user.json` | USR-00004 — 3 completions, `usage_confidence=0.6` |
| `heavy_usage_user.json` | USR-00025 — 9 completions, `usage_confidence=1.0` |
