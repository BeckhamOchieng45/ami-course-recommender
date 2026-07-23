# AMI Course Recommendation Engine

> **GitHub:** [github.com/BeckhamOchieng45/ami-course-recommender](https://github.com/BeckhamOchieng45/ami-course-recommender)

Intelligent course recommendation service for the AMI AI Coach Bot. Admins sign in to a dashboard, browse learners in a sidebar, and see each learner's personalised ranked course recommendations with AI-powered coaching reasons and a live chat for deeper explanation.

---

## Table of Contents

- [Quick Start — Local (SQLite)](#quick-start--local-sqlite)
- [Quick Start — Docker + Postgres](#quick-start--docker--postgres)
- [Default Login Credentials](#default-login-credentials)
- [Environment Variables](#environment-variables)
- [Authentication](#authentication)
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

# 5. Generate synthetic data + superuser
uv run python datagen/generate.py

# 6. Start the development server
uv run python manage.py runserver
```

Open **http://127.0.0.1:8000** — you'll be redirected to the login page.

---

## Quick Start — Docker + Postgres

Requires Docker and either Docker Desktop or [Colima](https://github.com/abiosoft/colima) running.

**M1/M2 Mac:** The compose file is already configured for `linux/arm64`.

```bash
# 1. Clone
git clone https://github.com/BeckhamOchieng45/ami-course-recommender.git
cd ami-course-recommender

# 2. Create your .env
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD and optionally GROQ_API_KEY

# 3. Build and start
docker-compose build
docker-compose up -d

# 4. Watch startup logs
docker-compose logs -f web
# You'll see:
#   ==> Postgres is up.
#   ==> Running migrations...
#   ==> Database is empty — seeding synthetic data (1000 users)...
#   ==> Superuser created: admin@email.com / password
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
docker-compose logs -f web
docker-compose logs -f db

# Shell inside the web container
docker-compose exec web bash

# Run Django management commands
docker-compose exec web python manage.py shell
docker-compose exec web python manage.py migrate

# Re-seed data (wipes and rebuilds)
docker-compose exec web python datagen/generate.py

# Run tests inside the container
docker-compose exec web python -m pytest

# Stop (data preserved)
docker-compose down

# Stop and wipe all data
docker-compose down -v

# Rebuild after dependency changes
docker-compose build --no-cache web
docker-compose up -d
```

### Dev mode (hot-reload inside Docker)

```bash
echo "DEV=1" >> .env
docker-compose up -d web
```

---

## Default Login Credentials

A superuser is created automatically on first run (both locally via `datagen/generate.py` and in Docker via the entrypoint).

| Field    | Value              |
|----------|--------------------|
| Email    | `admin@email.com`  |
| Password | `password`         |

**Change these before any non-local deployment.**

---

## Environment Variables

Copy `.env.example` to `.env`. The `.env` file is gitignored — never commit it.

```bash
cp .env.example .env
```

### Complete variable reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | No | — | Groq API key ([console.groq.com](https://console.groq.com)). Enables `coaching_reason` enhancement and `/api/chat` streaming. Falls back to templated reasons silently when absent. |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Groq model. Override e.g. `llama-3.3-70b-versatile`. |
| `POSTGRES_DB` | Docker only | `ami` | PostgreSQL database name. |
| `POSTGRES_USER` | Docker only | `ami` | PostgreSQL username. |
| `POSTGRES_PASSWORD` | Docker only | — | PostgreSQL password. **Change before any non-local deployment.** |
| `POSTGRES_HOST` | Docker only | `db` | Set automatically by docker-compose. Leave blank for local SQLite dev. |
| `POSTGRES_PORT` | Docker only | `5432` | PostgreSQL port. |
| `ALLOWED_HOSTS` | No | — | Comma-separated extra hostnames. `localhost` and `127.0.0.1` are always included. |
| `GUNICORN_WORKERS` | No | `3` | Gunicorn worker processes. Rule of thumb: `2 × CPUs + 1`. |
| `GUNICORN_TIMEOUT` | No | `120` | Worker timeout in seconds. |
| `DEV` | No | `0` | Set `1` inside Docker to use `runserver` with live reload. |

### Database selection

| Condition | Backend |
|---|---|
| `POSTGRES_HOST` set in environment | PostgreSQL |
| `POSTGRES_HOST` absent | SQLite (`db.sqlite3`) |
| Running `pytest` | SQLite always (forced in `conftest.py`) |

---

## Authentication

All API endpoints except `/api/auth/login` and `/api/auth/refresh` require a JWT Bearer token.

### Sign in

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@email.com", "password": "password"}'
```

Response:

```json
{
  "access":  "<access_token>",
  "refresh": "<refresh_token>",
  "user": { "id": 1, "email": "admin@email.com", "name": "Admin AMI", "is_staff": true }
}
```

### Use the token

Pass the access token as a Bearer header on every subsequent request:

```bash
curl http://localhost:8000/api/users/USR-00001/recommendations \
  -H "Authorization: Bearer <access_token>"
```

### Refresh an expired token

```bash
curl -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh_token>"}'
```

### Token lifetimes

| Token | Lifetime |
|---|---|
| Access | 8 hours |
| Refresh | 7 days |

---

## API Reference

All endpoints require `Authorization: Bearer <token>` unless noted.

### `POST /api/auth/login` — public

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@email.com", "password": "password"}'
```

### `POST /api/auth/refresh` — public

```bash
curl -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh_token>"}'
```

### `GET /api/auth/me`

```bash
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <token>"
```

### `GET /api/learners`

Paginated learner list with profile stats.

| Param | Default | Description |
|---|---|---|
| `page` | `1` | Page number |
| `page_size` | `25` | Results per page (max 100) |
| `search` | — | Filter on user_id, stated_goal, industry |
| `signal` | — | Filter by signal mode: `cold-start`, `blended`, `behavioral` |

```bash
curl "http://localhost:8000/api/learners?page=1&signal=cold-start" \
  -H "Authorization: Bearer <token>"
```

Response:

```json
{
  "total": 226, "page": 1, "page_size": 25, "pages": 10,
  "learners": [
    {
      "user_id": "USR-00001",
      "display_name": "Entrepreneur #1",
      "initials": "MB",
      "role": "Micro-Business Owner",
      "seniority": "Micro-Entrepreneur",
      "industry": "Retail",
      "company_size": "micro",
      "stated_goal": "improve my cash flow management...",
      "completed_courses": 0,
      "total_events": 0,
      "signal_mode": "cold-start",
      "usage_confidence": 0.0
    }
  ]
}
```

### `GET /api/users/{user_id}/recommendations`

| Param | Default | Description |
|---|---|---|
| `n` | `5` | Number of recommendations (1–20) |

```bash
curl "http://localhost:8000/api/users/USR-00001/recommendations?n=3" \
  -H "Authorization: Bearer <token>"
```

Response fields:

| Field | Description |
|---|---|
| `usage_confidence` | `0.0` = cold-start, `1.0` = fully behavior-driven |
| `llm_enhanced` | `true` if Groq enhanced the reasons |
| `reason` | Deterministic template — always present, auditable |
| `coaching_reason` | Groq-enhanced coaching voice. Equals `reason` when Groq is off |
| `reason_driver` | `survey` / `usage` / `context` / `cohort` / `fallback` |
| `score_breakdown` | Per-component raw score, effective weight, contribution |

### `POST /api/chat`

Streams a coaching conversation about a specific recommendation via SSE.

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "USR-00001",
    "question": "Why is this course right for me?",
    "recommendation": { ...full rec object... },
    "history": []
  }'
```

Response is `text/event-stream`:

```
data: Because\n\n
data:  you completed...\n\n
data: [DONE]\n\n
```

Requires `GROQ_API_KEY`. Returns a fallback message explaining this if the key is absent.

---

## UI

### Login page — `http://localhost:8000/login`

Two-panel design: AMI brand + stats on the left, sign-in form on the right. Pre-filled with default credentials.

### Dashboard — `http://localhost:8000`

- **Sidebar** — full learner list with human-readable display names (e.g. "Manager #42"), role initials avatar, industry, completion count, signal-mode badge. Search by goal/industry, filter by signal mode (cold-start / blended / behavioral), paginate with next/prev.
- **Learner header** — when a learner is selected, shows their display name, signal-mode badge, role, industry, seniority, and stated goal as a quoted line.
- **Recommendation cards** — ranked results with score donut, coaching reason, signal contribution bar, skill tags, "Why?" and "Ask coach" buttons.
- **Why? panel** — click any card or "Why?" to see the full score breakdown, signal weights, cold-start formula, and course details.
- **AI Coach chat** — "Ask coach" opens a streaming conversation. The coach knows the learner's profile, history, and exactly why the course was recommended. Markdown rendered in responses.

---

## Running Tests

Tests always use SQLite regardless of `.env` (isolated in `conftest.py`).

```bash
# Local
uv run pytest

# Inside Docker
docker-compose exec web python -m pytest

# Specific file
uv run pytest tests/test_auth.py -v
uv run pytest tests/test_scorers.py -v
```

**144 tests, 1 skipped** across: data generation, scoring, filtering, cold-start blending, explainability, API endpoints, JWT authentication, learner list.

---

## Project Structure

```
ami-course-recommender/
├── ami_course_recommendations/   # Django app
│   ├── models.py                 # Course, User, UsageEvent, SurveyResponse
│   ├── auth_views.py             # LoginView, TokenRefreshView, MeView, LearnerListView
│   ├── views.py                  # GET /api/users/{id}/recommendations
│   ├── chat_view.py              # POST /api/chat  (SSE streaming)
│   └── urls.py                   # All API routes
├── engine/                       # Pure scoring logic (no Django dependencies)
│   ├── scorers.py                # Pluggable scorer registry + 3 components
│   ├── coldstart.py              # Cold-start blending + score aggregation
│   ├── filters.py                # Hard filters + fairness invariant
│   ├── explainer.py              # Reason string generation + LLM enhancement
│   └── llm.py                    # Groq client (enhance_reason, stream_chat)
├── datagen/
│   └── generate.py               # Synthetic data generator + superuser creation
├── tests/                        # 144 tests
│   ├── test_datagen.py
│   ├── test_scorers.py
│   ├── test_filters.py
│   ├── test_coldstart.py
│   ├── test_explainer.py
│   ├── test_api.py
│   └── test_auth.py              # JWT auth + learner list tests (25 tests)
├── sample_outputs/               # Annotated real API responses
├── ui/
│   ├── login.html                # AMI-branded two-panel login page
│   ├── index.html                # Dashboard: learner sidebar + recommendations
│   └── ami-logo.avif             # AMI logo (fallback; primary via Wix CDN)
├── Dockerfile                    # Multi-stage, non-root, linux/arm64
├── docker-compose.yml            # Postgres 16 + web, ARM64-native
├── entrypoint.sh                 # migrate → seed → superuser → collectstatic → serve
├── .env.example                  # All variables documented
├── conftest.py                   # Forces SQLite for pytest
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

### Cold-start blending

```python
usage_confidence = min(1.0, completed_courses / 5)
w_usage   = 0.40 × usage_confidence
w_survey  = 0.35 + 0.40 × (1 - usage_confidence) × 0.60
w_context = 0.25 + 0.40 × (1 - usage_confidence) × 0.40
```

At zero completions: survey 59%, context 41%, usage 0%.  
At 5+ completions: all three at base weights.

### Filtering

Hard-excluded before scoring: already completed (≥95% progress), in-progress, unmet prerequisites. Level mismatch is a soft penalty. `is_paid` has zero weight.

### Auth

`djangorestframework-simplejwt` issues 8-hour access tokens and 7-day refresh tokens. A shared `jwt_required` decorator enforces authentication on the existing plain Django views without requiring a full DRF APIView rewrite.

See [WRITEUP.md](WRITEUP.md) for full design rationale and scaling plan.

---

## Sample Outputs

| File | User | Scenario |
|---|---|---|
| `sample_outputs/cold_start_user.json` | USR-00839 | `usage_confidence=0.0` — survey + context only |
| `sample_outputs/in_between_user.json` | USR-00004 | `usage_confidence=0.6` — blended signals |
| `sample_outputs/heavy_usage_user.json` | USR-00025 | `usage_confidence=1.0` — fully behavior-driven |
