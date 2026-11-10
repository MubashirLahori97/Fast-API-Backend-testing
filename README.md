# Genesis Health Backend API

FastAPI backend for Your Oracle Clinician. The plan and design decisions are in [docs/PLAN.md](docs/PLAN.md).

## Run locally

Install [uv](https://docs.astral.sh/uv/) and [Docker](https://www.docker.com/), then:

```bash
cp .env.example .env
docker compose up -d
uv sync
uv run alembic upgrade head
uv run fastapi dev app/main.py
```

Open http://127.0.0.1:8000/docs to try the endpoints.

Background jobs (emails, reminders) run in a separate process:

```bash
uv run python -m app.worker
```

## Tests and linting

The tests need the Docker database running. Each run rebuilds a separate `genesis_health_test` database from the migrations.

```bash
uv run pytest
uv run ruff check --fix .
uv run ruff format .
```

## Changing the database

1. Change or add a model (new models modules also go in `app/models.py`).
2. `uv run alembic revision --autogenerate -m "describe the change"`
3. Read the new file in `migrations/versions/` and fix anything autogenerate missed (triggers, functions, data changes).
4. `uv run alembic upgrade head`
