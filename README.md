# AMI Course Recommendation Engine

> **GitHub:** [github.com/BeckhamOchieng45/ami-course-recommender](https://github.com/BeckhamOchieng45/ami-course-recommender)

Intelligent course recommendation service for the AMI AI Coach Bot. Given a learner, it returns ranked course recommendations with confidence scores, human-readable coaching reasons, and a streaming AI chat that explains the reasoning in plain language.

```
"Because you told us you want to improve cash flow management and completed
 Intro to Bookkeeping, we suggest Cash Flow Forecasting for Small Businesses."
```

---

## Table of Contents

- [Quick Start — Local (SQLite)](#quick-start--local-sqlite)
- [Quick Start — Docker + Postgres](#quick-start--docker--postgres)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [UI](#ui)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Sample Outputs](#sample-outputs)

---

## Quick Start — Local (SQLite)

No Docker required. Uses SQLite by default.

```bash
# 1. Clone
git clone https://github.com/BeckhamOchieng45/ami-course-recommender.git
cd ami-course-recommender

# 2. Copy env file and add your Groq key (optional but recommended)
cp .env.example .env

# 3. Install dependencies (requires Python 3.13+ and uv)
uv sync

# 4. Run database migrations
uv run python manage.py migrate

# 5. Generate synthetic data (84 courses, 1,000 users, ~3,900 events)
uv run python datagen/generate.py

# 6. Start the development server
uv run python manage.py runserver
```

Open **http://127.0.0.1:8000** — the UI loads automatically.

---

## Quick Start — Docker + Postgres

Requires [Docker](https://docs.docker.com/get-docker/) and either Docker Desktop or [Colima](https://github.com/abiosoft/colima) running.

**M1/M2 Mac note:** The compose file is already configured for `linux/arm64`. No extra flags needed.

```bash
# 1. Clone
git clone https://github.com/BeckhamOchieng45/ami-course-recommender.git
cd ami-course-recommender

# 2. Create your .env from the example
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD and GROQ_API_KEY

# 3. Build and start all services (Postgres + Django/Gunicorn)
docker-compose build
docker-compose up -d

# 4. Watch logs until startup is complete
docker-compose logs -f web
# You'll see:
#   ==> Postgres is up.
#   ==> Running migrations...
#   ==> Database is empty — seeding synthetic data (1000 users)...
#   ==> Starting gunicorn...

# 5. Open the app
open http://localhost:8000
```

### Useful Docker commands

```bash
# View running services
docker-compose ps

# Tail logs
docker-compose logs -f
docker-compose logs -f web   # web service only
docker-compose logs -f db    # Postgres only

# Open a shell inside the web container
docker-compose exec web bash

# Run Django management commands inside the container
docker-compose exec web python manage.py shell
docker-compose exec web python manage.py migrate

# Re-seed data (wipes and rebuilds the dataset)
docker-compose exec web python datagen/generate.py

# Run tests inside the container
docker-compose exec web python -m pytest

# Stop services (data is preserved in the postgres_data volume)
docker-compose down

# Stop and wipe all data (destructive — removes the Postgres volume)
docker-compose down -v

# Rebuild the web image after dependency changes
docker-compose build --no-cache web
docker-compose up -d
```

### Dev mode inside Docker (hot-reload)

```bash
# Set DEV=1 in .env, then restart
echo "DEV=1" >> .env
docker-compose up -d web
```

This swaps gunicorn for Django's `runserver` with live code reloading. Source code directories are bind-mounted so edits on the host appear immediately in the container.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values. The `.env` file is gitignored — never commit it.

```bash
cp .env.example .env
```

### All variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | No | — | Groq API key. Get one at [console.groq.com](https://console.groq.com). When set, every recommendation's `coaching_reason` is enhanced by the AI coach and the `/api/chat` streaming endpoint activates. When absent, falls back to templated reasons — no errors. |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Groq model to use. Override if you want a different model (e.g. `llama-3.3-70b-versatile`). |
| `POSTGRES_DB` | Docker only | `ami` | PostgreSQL database name. |
| `POSTGRES_USER` | Docker only | `ami` | PostgreSQL username. |
| `POSTGRES_PASSWORD` | Docker only | — | PostgreSQL password. **Change this in any non-local deployment.** |
| `POSTGRES_HOST` | Docker only | `db` | PostgreSQL hostname. Set automatically by docker-compose; leave as `db` unless using an external database. |
| `POSTGRES_PORT` | Docker only | `5432` | PostgreSQL port. |
| `ALLOWED_HOSTS` | No | — | Comma-separated extra hostnames for Django's `ALLOWED_HOSTS`. Example: `myapp.example.com,api.example.com`. Localhost and 127.0.0.1 are always included. |
| `GUNICORN_WORKERS` | No | `3` | Number of gunicorn worker processes. Rule of thumb: `2 × CPU cores + 1`. |
| `GUNICORN_TIMEOUT` | No | `120` | Gunicorn worker timeout in seconds. Increase if you have slow LLM calls. |
| `DEV` | No | `0` | Set to `1` to use Django's `runserver` instead of gunicorn inside Docker. |

### Database selection logic

The app chooses its database backend automatically:

| Condition | Database used |
|---|---|
| `POSTGRES_HOST` is set in env | PostgreSQL |
| `POSTGRES_HOST` is not set | SQLite (`db.sqlite3`) |
| Running tests (`pytest`) | SQLite always (via `TEST_USE_SQLITE=1` in `conftest.py`) |

This means `uv run python manage.py runserver` always uses SQLite locally, while Docker always uses Postgres — with no manual config changes required.

---

## API Reference

### `GET /api/users/{user_id}/recommendations`

Returns top-N ranked course recommendations for a learner.

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `n` | integer | `5` | Number of recommendations to return (1–20) |

**Example**

```bash
curl "http://localhost:8000/api/users/USR-00001/recommendations?n=3"
```

**Response shape**

```json
{
  "user_id": "USR-00001",
  "usage_confidence": 1.0,
  "llm_enhanced": true,
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
        "skills_taught": ["KPI tracking", "performance reviews", "coaching conversations"]
      },
      "score": 0.7616,
      "usage_confidence": 1.0,
      "reason": "Because you told us you want to improve coaching conversations, we suggest \"KPI Design for Non-Finance Managers\".",
      "coaching_reason": "Your focus on coaching conversations makes this a natural next step — this module gives you the practical tools to run meaningful performance conversations straight away.",
      "reason_detail": "Your survey identified coaching conversations as a priority...",
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

**Response fields**

| Field | Description |
|---|---|
| `usage_confidence` | 0.0 = cold-start (no usage history), 1.0 = fully behavior-driven |
| `llm_enhanced` | `true` if `GROQ_API_KEY` is set and Groq enhanced the reasons |
| `reason` | Deterministic templated reason — always present, fully auditable |
| `coaching_reason` | Groq-enhanced coaching version. Equals `reason` when Groq is not configured |
| `reason_driver` | Which signal drove the recommendation: `survey`, `usage`, `context`, `cohort`, or `fallback` |
| `score_breakdown` | Per-component raw score, effective weight, and contribution to final score |

**Error responses**

| Status | Condition |
|---|---|
| `404` | Unknown `user_id` |
| `400` | `n` is not an integer, or outside 1–20 |

---

### `POST /api/chat`

Streams a coaching conversation about a specific recommendation via Server-Sent Events (SSE).

**Request body**

```json
{
  "user_id": "USR-00001",
  "question": "Why is this course right for me specifically?",
  "recommendation": { },
  "history": [
    {"role": "user",      "content": "Previous question"},
    {"role": "assistant", "content": "Previous answer"}
  ]
}
```

The `recommendation` field should be the full recommendation object from the `/recommendations` response. The `history` array is optional and capped at the last 10 turns.

**Response:** `text/event-stream` (SSE)

```
data: Because\n\n
data:  you\n\n
data:  completed...\n\n
data: [DONE]\n\n
```

Each `data:` line is a text chunk. `[DONE]` signals the end of the stream. `[ERROR] <message>` signals a failure.

**Note:** Requires `GROQ_API_KEY` to be set. Returns a fallback message explaining this if the key is absent.

---

## UI

Open **http://localhost:8000** in a browser.

### Features

- **Recommendation cards** — ranked results with signal-contribution bar, coaching reason, and skill tags
- **Why? panel** — click any card to see the full score breakdown, cold-start formula, signal weights, and course details
- **AI Coach chat** — click "Ask coach" on any card to open a streaming conversation. The coach knows your profile, learning history, and exactly why the course was recommended. Powered by Groq (`openai/gpt-oss-120b`). Markdown rendered in responses.
- **Signal weight sidebar** — live animated bars showing this user's effective signal weights after cold-start blending
- **Sample users** — header quicklinks for cold-start, in-between, and heavy-usage scenarios

---

## Running Tests

Tests always use SQLite regardless of `.env` settings (isolated via `conftest.py`).

```bash
# Local
uv run pytest

# Inside Docker
docker-compose exec web python -m pytest

# Specific test file
uv run pytest tests/test_scorers.py -v

# With output
uv run pytest -v --tb=short
```

**119 tests** across: data generation, scoring components, filtering, cold-start blending, explainability layer, and API endpoints.

---

## Project Structure

```
ami-course-recommender/
├── ami_course_recommendations/   # Django app
│   ├── models.py                 # Course, User, UsageEvent, SurveyResponse
│   ├── views.py                  # GET /api/users/{id}/recommendations
│   ├── chat_view.py              # POST /api/chat  (SSE streaming)
│   └── urls.py
├── engine/                       # Pure scoring logic (no Django dependencies)
│   ├── scorers.py                # Pluggable scorer registry + 3 components
│   ├── coldstart.py              # Cold-start blending + score aggregation
│   ├── filters.py                # Hard filters + fairness invariant
│   ├── explainer.py              # Reason string generation + LLM enhancement
│   └── llm.py                    # Groq client (enhance_reason, stream_chat)
├── datagen/
│   └── generate.py               # Synthetic data generator (1,000 users)
├── tests/                        # 119 tests, one file per feature
│   ├── test_datagen.py
│   ├── test_scorers.py
│   ├── test_filters.py
│   ├── test_coldstart.py
│   ├── test_explainer.py
│   └── test_api.py
├── sample_outputs/               # Real API output for 3 representative users
│   ├── cold_start_user.json
│   ├── in_between_user.json
│   └── heavy_usage_user.json
├── ui/
│   └── index.html                # Single-page UI (Tailwind CDN, no build step)
├── Dockerfile                    # Multi-stage build, non-root user
├── docker-compose.yml            # Postgres + web services, ARM64-native
├── entrypoint.sh                 # Wait → migrate → seed → collectstatic → serve
├── .env.example                  # All variables documented
├── pyproject.toml                # Dependencies (uv)
├── DESIGN.md                     # Pre-implementation design decisions
└── WRITEUP.md                    # Approach, tradeoffs, experiment design, scaling
```

---

## How It Works

### Scoring

Three components run in parallel for every eligible (user, course) pair:

| Component | Base weight | Signal |
|---|---|---|
| Survey match | 0.35 | Weighted Jaccard: user's goals + skill-gaps ↔ course skill tags |
| Usage-based | 0.40 | Content similarity to completed courses + cohort popularity |
| Work-context | 0.25 | Seniority–level fit + industry–programme affinity |

### Cold-start

New users have zero usage history. Rather than branching, the engine blends weights continuously:

```
usage_confidence = min(1.0, completed_courses / 5)
w_usage   = 0.40 × usage_confidence
w_survey  = 0.35 + 0.40 × (1 - usage_confidence) × 0.60
w_context = 0.25 + 0.40 × (1 - usage_confidence) × 0.40
```

At zero completions, survey carries 59% and work-context 41%. At 5+ completions, all three are at base weights.

### Filtering

Hard-excluded before scoring (never wastes a scorer call on ineligible courses):
- Already completed (progress ≥ 95%)
- In-progress (started, not completed)
- Unmet prerequisites

**Level mismatch** is a soft penalty in the work-context scorer, not a hard filter — a strong survey or usage signal should be able to surface an advanced course for a motivated entry-level learner.

**`is_paid` has zero weight** — free and certificate courses are treated identically (AMI's low-cost-access mission).

### Explainability

Every recommendation carries:
- `reason` — deterministic, templated, fully auditable
- `coaching_reason` — Groq-enhanced coaching voice (falls back to `reason` silently)
- `score_breakdown` — per-component contribution for live debugging

### AI Chat

`POST /api/chat` builds a context-rich system prompt from the learner's profile, the specific course, and the score breakdown, then streams the response from Groq token-by-token via SSE. Conversation history is maintained client-side and capped at 10 turns server-side.

See [WRITEUP.md](WRITEUP.md) for full design rationale, experiment design, and scaling plan to 10k+ users.

---

## Sample Outputs

Three annotated real API responses in `sample_outputs/`:

| File | User | Scenario |
|---|---|---|
| `cold_start_user.json` | USR-00839 | Zero usage history — survey + work-context only, `usage_confidence=0.0` |
| `in_between_user.json` | USR-00004 | 3 completions — blended signals, `usage_confidence=0.6` |
| `heavy_usage_user.json` | USR-00025 | 9 completions — fully behavior-driven, `usage_confidence=1.0` |

Each file includes a `_meta` block explaining what the scenario demonstrates and what to look for in the score breakdown.
