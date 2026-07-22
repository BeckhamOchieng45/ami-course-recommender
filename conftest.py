"""
Root conftest — applied to every test session.

Forces SQLite for all pytest runs regardless of what POSTGRES_HOST
is set to in .env. This means:
  - Tests run locally without Docker (no Postgres needed)
  - docker-compose still uses Postgres (POSTGRES_HOST=db is set in
    the container environment, but pytest sets TEST_USE_SQLITE=1 there
    too if you run tests inside the container — add it to the compose
    command if needed)
"""

import os

# Must be set before Django imports settings
os.environ.setdefault("TEST_USE_SQLITE", "1")
