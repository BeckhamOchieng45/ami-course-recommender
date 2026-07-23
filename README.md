# AMI Course Recommendation Engine

> **GitHub:** [github.com/BeckhamOchieng45/ami-course-recommender](https://github.com/BeckhamOchieng45/ami-course-recommender)

Intelligent course recommendation service for the AMI AI Coach Bot. Admins sign in to a dashboard, browse 1,000 learners in a sidebar, and see each learner's personalised ranked course recommendations — with AI-powered coaching reasons, score breakdowns, and a live streaming chat for deeper explanation.

---

## Features

### Recommendation Engine
- **Three scoring signals** — Survey match (0.35), Usage-based (0.40), Work-context (0.25)
- **Continuous cold-start blending** — No hard branches; each completed course adds 1/5th of the usage signal's weight
- **Pluggable scorer registry** — Adding a new signal is one function + one decorator; nothing else changes
- **Cohort popularity bridge** — Cold-start users get a usage signal via peer-group completions
- **Hard filters** — Completed courses (≥95% progress), in-progress courses, and unmet prerequisites excluded before scoring
- **Soft level penalty** — Level mismatch reduces score but never hard-blocks a course
- **Fairness invariant** — `is_paid` has zero weight; free and certificate courses treated identically

### Explainability
- **Deterministic `reason`** — Templated, auditable, traceable to exact data points
- **`coaching_reason`** — Groq re-voices the reason in AMI's coaching tone (graceful fallback when key absent)
- **`score_breakdown`** — Per-component raw score, effective weight, and contribution exposed in every API response
- **`reason_driver`** — Which signal led the recommendation: `survey` / `usage` / `context` / `cohort` / `fallback`

### AI Coach (Groq `openai/gpt-oss-120b`)
- **`coaching_reason` enhancement** — Every recommendation enriched with coaching tone
- **`POST /api/chat` streaming** — SSE conversation with full learner + course context in the system prompt
- **Markdown rendering** — Responses render with bold, bullets, code blocks in the UI
- **Graceful degradation** — No `GROQ_API_KEY` → falls back silently, no errors anywhere

### Authentication & Security
- **JWT via simplejwt** — Access tokens (8h), refresh tokens (7d)
- **All endpoints protected** — `Authorization: Bearer <token>` required
- **Superuser auto-created** — `admin@email.com` / `password` on first run
- **`jwt_required` decorator** — Guards existing plain Django views without full DRF rewrite

### Dashboard UI
- **Login page** (`/login`) — Two-panel AMI-branded layout, pre-filled credentials
- **Learner sidebar** — 1,000 learners with display names ("Manager #42"), role initials, industry, completion count, signal-mode badge
- **Search & filter** — Real-time search by goal/industry, filter by cold-start/blended/behavioral, paginated
- **Recommendation cards** — Score donut, stacked signal bar, coaching reason, skill tags
- **"Why?" panel** — Full score breakdown, cold-start formula with live numbers, course details
- **AI Coach chat** — Streaming conversation, markdown, conversation history, suggested questions
- **Escape to close** — Keyboard shortcut closes any open panel

### Infrastructure
- **Multi-stage Dockerfile** — `python:3.13-slim`, non-root `ami` user, `linux/arm64` for M1/M2
- **Docker Compose** — Postgres 16-alpine + gunicorn web service, healthcheck, ARM64-native
- **`entrypoint.sh`** — Waits for Postgres (pure Python socket check), migrate → seed → superuser → collectstatic → serve
- **SQLite fallback** — `POSTGRES_HOST` absent → SQLite; pytest always uses SQLite
- **Dev mode** — `DEV=1` swaps gunicorn for `runserver` with live code reload inside Docker

### Synthetic Data
- **1,000 learners** — 4 AMI roles, 8 industries, realistic distribution
- **84 courses** — 5 programme areas, AMI-specific skill tags ("cash flow forecasting" not "finance")
- **~3,900 events** — 70% in-domain, ~20% drop rate, cold-start/typical/heavy-user cohorts
- **Hidden `true_interest`** — Ground truth variable for verifying engine correctness

### Testing
- **144 tests, 1 skipped** — Every feature covered
- **Relative rankings tested** — Not just "returns 200"; scorers tested against known correct ordering
- **LLM patched in tests** — `enhance_reason` mocked so CI never hits the Groq API

---

## Table of Contents

- [Quick Start — Local (SQLite)](#quick-start--local-sqlite)
- [Quick Start — Docker + Postgres](#quick-start--docker--postgres)
- [Default Login Credentials](#default-login-credentials)
- [Environment Variables](#environment-variables)
- [Authentication](#authentication)
- [API Reference](#api-reference)
- [UI Walkthrough](#ui-walkthrough)
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

# 2. Copy env file and optionally add your Groq key
cp .env.example .env

# 3. Install dependencies (requires Python 3.13+ and uv)
uv sync

# 4. Run database migrations
uv run python manage.py migrate

# 5. Generate synthetic data + superuser (1,000 learners, 84 courses)
uv run python datagen/generate.py

# 6. Start the development server
uv run python manage.py runserver
```

Open **http://127.0.0.1:8000** — you'll be redirected to the login page.  
Sign in with `admin@email.com` / `password`.

---

## Quick Start — Docker + Postgres

Requires Docker and either Docker Desktop or [Colima](https://github.com/abiosoft/colima) running.

**M1/M2 Mac:** The compose file is pre-configured for `linux/arm64`.

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

# 4. Watch startup (takes ~30s on first run to seed data)
docker-compose logs -f web
# You'll see:
#   ==> Postgres is up.
#   ==> Running migrations...
#   ==> Database is empty — seeding synthetic data (1000 users)...
#   ==> Superuser created: admin@email.com / password
#   ==> Starting gunicorn...

# 5. Open
open http://localhost:8000
```

### Useful Docker commands

```bash
# Status
docker-compose ps

# Logs
docker-compose logs -f web
docker-compose logs -f db

# Shell inside container
docker-compose exec web bash

# Run a management command
docker-compose exec web python manage.py shell
docker-compose exec web python manage.py migrate

# Re-seed data (wipes and rebuilds)
docker-compose exec web python datagen/generate.py

# Run the test suite inside the container
docker-compose exec web python -m pytest

# Stop (data preserved in postgres_data volume)
docker-compose down

# Stop and wipe all data
docker-compose down -v

# Rebuild after dependency changes
docker-compose build --no-cache web
docker-compose up -d
```

### Dev mode inside Docker

```bash
echo "DEV=1" >> .env
docker-compose up -d web
# Reloads code on save via bind-mounted source dirs
```

---

## Default Login Credentials

Created automatically on first run — both locally (`datagen/generate.py`) and in Docker (`entrypoint.sh`).

| Field    | Value             |
|----------|-------------------|
| Email    | `admin@email.com` |
| Password | `password`        |

**Change before any non-local deployment.**

---

## Environment Variables

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | No | — | Groq API key ([console.groq.com](https://console.groq.com)). Enables `coaching_reason` and `/api/chat`. Falls back silently when absent. |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Groq model. Override e.g. `llama-3.3-70b-versatile`. |
| `POSTGRES_DB` | Docker only | `ami` | PostgreSQL database name. |
| `POSTGRES_USER` | Docker only | `ami` | PostgreSQL username. |
| `POSTGRES_PASSWORD` | Docker only | — | **Change before any non-local deployment.** |
| `POSTGRES_HOST` | Docker only | `db` | Set automatically by docker-compose. Leave blank for local SQLite dev. |
| `POSTGRES_PORT` | Docker only | `5432` | PostgreSQL port. |
| `ALLOWED_HOSTS` | No | — | Comma-separated extra hostnames. `localhost` / `127.0.0.1` always included. |
| `GUNICORN_WORKERS` | No | `3` | Worker processes. Rule of thumb: `2 × CPUs + 1`. |
| `GUNICORN_TIMEOUT` | No | `120` | Worker timeout in seconds. |
| `DEV` | No | `0` | Set `1` in Docker to use `runserver` with live reload. |

### Database selection logic

| Condition | Backend used |
|---|---|
| `POSTGRES_HOST` set in environment | PostgreSQL |
| `POSTGRES_HOST` absent | SQLite (`db.sqlite3`) |
| Running `pytest` | SQLite always (forced by `conftest.py`) |

---

## Authentication

All endpoints except `/api/auth/login` and `/api/auth/refresh` require a JWT Bearer token.

### Sign in

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@email.com", "password": "password"}'
```

```json
{
  "access":  "<access_token>",
  "refresh": "<refresh_token>",
  "user": { "id": 1, "email": "admin@email.com", "name": "Admin AMI", "is_staff": true }
}
```

### Use the token

```bash
curl http://localhost:8000/api/learners \
  -H "Authorization: Bearer <access_token>"
```

### Refresh

```bash
curl -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh_token>"}'
```

| Token | Lifetime |
|---|---|
| Access | 8 hours |
| Refresh | 7 days |

---

## API Reference

All endpoints require `Authorization: Bearer <token>` unless marked public.

### `POST /api/auth/login` — public
Email + password → access + refresh tokens.

### `POST /api/auth/refresh` — public
Refresh token → new access token.

### `GET /api/auth/me`
Returns authenticated user's profile (`id`, `email`, `name`, `is_staff`).

### `GET /api/learners`

| Param | Default | Description |
|---|---|---|
| `page` | `1` | Page number |
| `page_size` | `25` | Results per page (max 100) |
| `search` | — | Filters on user_id, stated_goal, industry |
| `signal` | — | `cold-start` / `blended` / `behavioral` |
| `role` | — | Filter by role slug |

```bash
curl "http://localhost:8000/api/learners?signal=cold-start&page=1" \
  -H "Authorization: Bearer <token>"
```

Each learner in the response includes `user_id`, `display_name` (e.g. "Entrepreneur #7"), `initials`, `role`, `industry`, `seniority`, `stated_goal`, `completed_courses`, `signal_mode`, `usage_confidence`.

### `GET /api/users/{user_id}/recommendations`

| Param | Default | Description |
|---|---|---|
| `n` | `5` | Number of recommendations (1–20) |

```bash
curl "http://localhost:8000/api/users/USR-00001/recommendations?n=5" \
  -H "Authorization: Bearer <token>"
```

Response top-level fields:

| Field | Description |
|---|---|
| `usage_confidence` | `0.0` cold-start → `1.0` fully behavior-driven |
| `llm_enhanced` | `true` if Groq is configured and enhanced the reasons |
| `recommendation_count` | Number of recs returned |

Each recommendation includes `position`, `score`, `reason`, `coaching_reason`, `reason_detail`, `reason_driver`, `score_breakdown`, and the full `course` object.

### `POST /api/chat`

Streams an AI coaching conversation about a recommendation via Server-Sent Events.

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "USR-00001",
    "question": "Why is this course right for me?",
    "recommendation": { ...full rec object from /recommendations... },
    "history": []
  }'
```

Stream format: `data: <chunk>\n\n` … `data: [DONE]\n\n`  
Error format: `data: [ERROR] <message>\n\n`

Requires `GROQ_API_KEY`. Returns an explanatory fallback message if the key is absent.

---

## UI Walkthrough

### `/login`
- AMI logo (Wix CDN, no build step required)
- Two-panel: brand + impact stats left, form right
- Pre-filled with `admin@email.com` / `password`
- Redirects immediately if a valid token is already in `localStorage`

### `/` — Dashboard

**Sidebar (left)**
- Learner list showing human-readable display names (e.g. "Manager #42", "Entrepreneur #7")
- Role-based avatar initials (MB, SM, CE, SE) with colour-coded backgrounds
- Industry and completion count per learner
- Signal-mode badge: 🟡 Cold-start / 🔵 Blended / 🟢 Behavioral
- Real-time search (debounced 300ms)
- Filter tabs: All / Cold-start / Blended / Behavioral
- Next/prev pagination

**Main panel (right)**
- Learner header: display name, signal-mode badge, role, industry, seniority, stated goal
- Number-of-results selector (3 / 5 / 10)
- Recommendation cards with:
  - Rank badge and score donut (SVG)
  - Course level chip, programme area, duration
  - Coaching reason (Groq-enhanced if key set)
  - Stacked signal contribution bar
  - Skill tags
  - **"Why?"** and **"Ask coach"** buttons

**Why? panel (slide-up)**
- Triggered by card click or "Why?" button
- Coach recommendation with Groq attribution if enhanced
- Primary signal explanation in plain English
- Animated per-component contribution bars
- Cold-start formula with this learner's exact numbers
- Full course details and skills taught

**AI Coach chat (slide-up)**
- Triggered by "Ask coach" button on any card or from within the Why? panel
- Welcome screen with 4 suggested starter questions
- Streaming tokens appear in real-time with blinking cursor
- Final response rendered as formatted markdown
- Conversation history persists per session; "Clear" resets it
- Escape key closes whichever panel is open

---

## Running Tests

Tests always use SQLite, regardless of `.env` (forced by `conftest.py`).

```bash
# All tests
uv run pytest

# Verbose
uv run pytest -v

# Specific file
uv run pytest tests/test_auth.py -v
uv run pytest tests/test_scorers.py -v

# Inside Docker
docker-compose exec web python -m pytest
```

**144 tests, 1 skipped** (skipped test checks Groq fallback — only valid when key is absent).

| File | Count | Covers |
|---|---|---|
| `test_datagen.py` | 16 | Hidden-interest correlation, drop rate, cold-start cohort |
| `test_scorers.py` | 23 | Relative rankings, weight verification, scorer registry |
| `test_filters.py` | 20 | Hard filters, prerequisites, fairness invariant (`is_paid`) |
| `test_coldstart.py` | 20 | Weight math, monotonicity, weights sum to 1.0 |
| `test_explainer.py` | 17 | Reason strings, coaching_reason fallback, markdown |
| `test_api.py` | 23 | Response shape, JWT guard, cold-start vs active users |
| `test_auth.py` | 25 | Login, refresh, /me, learner list, signal filters, display names |

---

## Project Structure

```
ami-course-recommender/
├── ami_course_recommendations/   # Django app
│   ├── models.py                 # Course, User, UsageEvent, SurveyResponse
│   ├── auth_views.py             # LoginView, TokenRefreshView, MeView, LearnerListView
│   ├── views.py                  # GET /api/users/{id}/recommendations  (JWT required)
│   ├── chat_view.py              # POST /api/chat  (SSE streaming, JWT required)
│   ├── urls.py                   # All API routes
│   └── migrations/
│
├── engine/                       # Pure scoring logic — zero Django dependencies
│   ├── scorers.py                # @register_scorer registry + 3 components
│   ├── coldstart.py              # Continuous cold-start blending + aggregation
│   ├── filters.py                # Hard exclusion filters + fairness invariant
│   ├── explainer.py              # Templated reasons + Groq coaching tone
│   └── llm.py                    # Groq client (enhance_reason, stream_chat)
│
├── datagen/
│   └── generate.py               # 1,000 users + 84 courses + superuser
│
├── tests/                        # 144 tests
│   ├── test_datagen.py           # 16 — data quality + hidden-interest correlation
│   ├── test_scorers.py           # 23 — scorer correctness
│   ├── test_filters.py           # 20 — filtering + fairness
│   ├── test_coldstart.py         # 20 — blending math
│   ├── test_explainer.py         # 17 — reason strings
│   ├── test_api.py               # 23 — HTTP layer
│   └── test_auth.py              # 25 — JWT auth + learner list
│
├── sample_outputs/               # Annotated real API responses
│   ├── cold_start_user.json      # usage_confidence=0.0
│   ├── in_between_user.json      # usage_confidence=0.6
│   └── heavy_usage_user.json     # usage_confidence=1.0
│
├── ui/
│   ├── login.html                # Two-panel AMI-branded login
│   ├── index.html                # Full dashboard (sidebar + recs + why + chat)
│   └── ami-logo.avif             # Logo fallback
│
├── Dockerfile                    # Multi-stage, non-root ami user, linux/arm64
├── docker-compose.yml            # postgres:16-alpine + web, ARM64-native
├── entrypoint.sh                 # wait → migrate → seed → superuser → serve
├── .env.example                  # All variables documented with inline comments
├── conftest.py                   # Forces TEST_USE_SQLITE=1 for all pytest runs
├── pytest.ini
├── pyproject.toml                # uv-managed dependencies
├── DESIGN.md                     # Pre-implementation design decisions
├── WRITEUP.md                    # Approach, tradeoffs, experiment design, scaling
└── PRESENTATION.md               # Technical slide deck (not committed)
```

---

## How It Works

### Three-signal scoring

Each eligible (user, course) pair is scored by three independent components:

| Component | Base weight | Signal |
|---|---|---|
| Survey match | 0.35 | Weighted Jaccard: goals (0.50) + skill_gaps (0.35) + preferred_topics (0.15) vs course tags |
| Usage-based | 0.40 | Tag Jaccard vs high-engagement completions + cohort popularity (capped 20%) |
| Work-context | 0.25 | Seniority→level fit (1.0/0.3) + industry→programme affinity (1.0/0.4) |

### Cold-start blending

```python
usage_confidence = min(1.0, completed_courses / 5)

w_usage   = 0.40 × usage_confidence
w_survey  = 0.35 + 0.40 × (1 − usage_confidence) × 0.60
w_context = 0.25 + 0.40 × (1 − usage_confidence) × 0.40
```

Zero completions: survey 59%, context 41%, usage 0%.  
Five+ completions: survey 35%, usage 40%, context 25%.

### Filtering (before scoring)

1. Already completed (progress ≥ 95%) — hard exclude
2. In-progress — hard exclude
3. Unmet prerequisites — hard exclude
4. Level mismatch — soft penalty (0.3 raw score instead of 1.0 in work-context)
5. `is_paid` — zero weight (fairness invariant, machine-tested)

### Explainability chain

```
engine/scorers.py  →  engine/coldstart.py  →  engine/filters.py
     ↓ ScoreResult        ↓ AggregatedScore
engine/explainer.py → build_reason() → reason (template)
                    → llm.enhance_reason() → coaching_reason (Groq)
```

### Authentication

`jwt_required` decorator on `RecommendationsView.get` and `ChatView.post`. Login uses Django's `authenticate()` by username (= email) with email-field fallback lookup.

---

## Sample Outputs

| File | Scenario | Key thing to notice |
|---|---|---|
| `cold_start_user.json` | `usage_confidence=0.0` | `usage_based.contribution=0.0` throughout; survey + context carry everything |
| `in_between_user.json` | `usage_confidence=0.6` | All three signals visible; context still outweighs usage at 60% confidence |
| `heavy_usage_user.json` | `usage_confidence=1.0` | Top reason is usage-driven ("Because you completed..."); behavior has taken over |
