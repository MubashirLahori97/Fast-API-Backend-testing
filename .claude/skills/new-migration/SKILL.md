---
name: new-migration
description: Creates an Alembic migration for this backend and makes it complete. It autogenerates, adds what autogenerate misses (check constraints, seed rows, data changes, triggers), has the migration-reviewer agent check it, then runs upgrade → downgrade → upgrade and the drift test. Use it whenever a model in app/**/models.py changes, or a table, column, constraint, index, default or seed row is added or changed, even if the user only says "add a column", "schema change", "update the models" or "alembic". Also use it when a story being built needs a database change.
---

# New migration

Autogenerate only diffs tables, columns, indexes, foreign keys and unique constraints. Everything else is easy to forget, and this project has shipped a migration without its check constraints more than once. This skill makes each migration complete, reversible and tested before it's committed.

The argument is a short lowercase description of the change, such as `add escalations` or `turn off and delete family members`. If none is given, write one from the model change.

## 1. Check the starting point

```bash
docker compose ps                   # Postgres must be up (port 5433)
uv run alembic current              # must equal...
uv run alembic heads                # ...this, a single head
```

If the database is behind, run `uv run alembic upgrade head` first. If there are two heads, stop and tell the user: two branches each added a migration, and they need merging (`alembic merge`) on purpose.

Make sure the new or changed models module is imported in `app/models.py`, or Alembic won't see it.

## 2. Generate

```bash
uv run alembic revision --autogenerate -m "<description>"
```

Read the whole generated file in `migrations/versions/`. If autogenerate found nothing, delete the empty file and look for why (usually a models module missing from `app/models.py`).

## 3. Add what autogenerate misses

Compare the file with the models and add, by hand:

- **Check constraints.** For each `CheckConstraint` on an existing table, use `op.create_check_constraint("ck_<table>_<what>", "<table>", "<sql>")` in `upgrade`, and `op.drop_constraint(..., type_="check")` at the **start** of `downgrade`. For new tables they're usually already inside `create_table`; confirm.
- **Seed rows** the code depends on (a policy version, a lookup table such as the age-of-majority table): use `op.bulk_insert(sa.table(...), [...])` in `upgrade` and a `DELETE` in `downgrade`. Seed reference data only, never health data.
- **Data changes:** update existing rows *before* adding a constraint they would break, such as renamed codes or a new allowed list.
- **Defaults and NOT NULL:** a new NOT NULL column on a table that has rows needs a `server_default` or a backfill.
- **Triggers, functions and extensions:** write them in `op.execute(...)`, and undo them in `downgrade`.

Keep lines at most 100 characters; split long SQL strings across lines. The post-edit hook runs ruff, but ruff can't split strings for you. For bigger edits, use the Edit tool or a script file in the scratchpad: in this repo's Git Bash, `\n` inside a heredoc'd Python script can be turned into real newlines.

## 4. Review

Ask the `migration-reviewer` agent to check the file. Give it the migration's path and the models you changed. Fix every "Must fix" it reports, and use judgment on the rest.

## 5. Run it both ways

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run pytest tests/test_migrations.py -q   # models and migrations agree
uv run ruff check migrations/
```

Running the downgrade proves the migration can be undone; the drift test proves nothing was left out of the models or the migration. The test database is rebuilt from all migrations on every `pytest` run, so the full suite also exercises it.

If something is wrong and the migration **hasn't been pushed**, it's fine to start over: `uv run alembic downgrade -1`, delete the file, fix the model, and generate again. Once a migration is pushed, other databases may have run it, so never edit it. The `protect_files` hook blocks that. Write a new migration on top instead.

## 6. Report

Tell the user, briefly:
- the revision id and file name;
- what it does, including what you added by hand and why;
- that the upgrade, downgrade and drift test passed (or what failed);
- anything destructive: dropped columns, or rows changed or deleted.

Don't commit unless the user asks.
