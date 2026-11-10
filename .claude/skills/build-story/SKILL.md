---
name: build-story
description: Builds one Client user story in this FastAPI backend from start to definition of done. It reads the story by title, builds the endpoints, models and migration, has test-writer write the tests and story-checker and security-reviewer review in parallel, fixes their findings, records decisions and open questions in docs/PLAN.md, and runs the full checks. Use it whenever the user asks to build, start, continue to or implement a story or a phase item ("build 3.2", "continue to 8.2", "start Phase R", "do the escalation story"), or to redo a story after the requirements changed.
---

# Build a story

Each story in `docs/PLAN.md` is done when it meets the plan's **Definition of done**: endpoints, schemas, models and a migration; tests for every scenario and message the backend owns; audit events; a clean `story-checker` report, and `security-reviewer` for anything touching auth, sessions or health data; and the plan updated. This skill is that loop. Each step exists because skipping it has cost a rework before.

The argument names the story or phase item, such as `3.2`, `Escalation / Emergency Detection` or `R1`.

## 1. Understand the story

- **Find the story by its title** in `docs/requirements/client-user-stories.md`. Numbers change between the BA's versions, and the stories' own "see story X.Y" links often use old numbers. The number map is in `docs/PLAN.md` under **Requirements update**.
- Read all of it: story details, acceptance criteria, alternate scenarios, non-functional requirements, and every validation message. Read the stories it refers to, by title.
- In `docs/PLAN.md`, read:
    - the story's phase entry;
    - earlier decisions it builds on;
    - **Assumed values**;
    - "Carried forward" items that name this story or phase;
    - the open questions it touches.
- **Sort what the story asks for** into four groups:
    - the backend's part;
    - the apps' part (screens, dialogs, wording the app shows itself);
    - the AI team's part (the Oracle's behaviour, behind `app/oracle/contract.py`);
    - what a later phase owns.

    Only the backend's part gets built, but the backend must give the others what they need.
- Check the branch: work on the phase's branch, never `main`.

## 2. Design, then build

- **Decide where things go.** Use the domain package the plan's code layout names: `router.py` stays thin, rules go in `service.py`. Reuse what exists:
    - `ClientSession` (the policy gate);
    - `OwnedProfile` / `UsableProfile` / `OwnedConversation` for ids;
    - `AppError` for every error the apps show;
    - `audit.record` for events;
    - `database_errors_retryable`;
    - `entitlements` checks;
    - `settings` for every tunable number.
- **Messages:** copy each one exactly from the story, typographic apostrophe (’) included. Where the story has no message, or two stories disagree, pick one and note it for step 6.
- **Health data:** never in logs, URLs, error messages, audit details, job payloads, or push and email text.
- **Locks and races:** rows with counters, single-use state or limits are read `FOR UPDATE`. A limit that's checked before an insert runs under a lock on the parent row.
- **Model changes:** use the `/new-migration` skill; it adds what autogenerate misses and tests the migration both ways.
- **Smoke test:** before handing off, run one end-to-end flow (a throwaway test file using the fixtures, deleted afterwards). Fix anything obvious first, so the reviewers spend their time on real problems.

## 3. Test and review, in parallel

Start these three agents in the background, in one message:

- **`test-writer`**: a new `tests/test_<story_slug>.py` whose docstring names the story. Brief it with:
    - every endpoint and its responses;
    - each behaviour to cover: happy path, each alternate scenario, each message with its exact text, ownership (another account's id → 404), and the policy gate (add new routes to the gate's route list in `tests/test_intake_self.py`);
    - "don't edit `app/`; report suspected app bugs".
- **`story-checker`**: give it the story title, the files, and your decisions list. Give it the scope (what's UI-only, the AI team's or deferred), so it judges rather than re-reports known splits.
- **`security-reviewer`**: for anything touching auth, sessions, tokens, profiles or health data (nearly every story). Point it at specific worries: ownership, races, health data in logs and errors, abuse and cost.

Don't edit app code while they run: the reviewers and the tests are reading it.

## 4. Fix what they found

- Fix every Critical and High finding, and every Medium unless it's a deliberate, recorded decision. Use judgment on Low ones; record what you leave.
- When a reviewer says the story contradicts one of your decisions, prefer the story, unless the story is ambiguous. In that case, record your reading as a decision and add an open question.
- After changing behaviour, send `test-writer` (continue it with SendMessage; it keeps its context) the exact list of what changed, so it updates the tests. A bug it reports is a real finding: fix it in the app.
- If the fixes added new mechanisms (concurrency, claims, background jobs, safety rules), ask `security-reviewer` for a focused second look at just those parts. Second reviews have caught real bugs here.

## 5. Final checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run alembic heads                 # one head
uv run pytest -q                     # about 3 minutes: give it a 10-minute timeout
```

All of them must pass before you report. If a test fails, say so with its output; don't call the story done.

## 6. Update the plan

In `docs/PLAN.md`:
- **Tick the story** in its phase, with a short list of its endpoints.
- **"Decisions made while building <story>":**
    - the design choices;
    - the stored codes;
    - every message not in the stories, with the situation it's for;
    - where the stories disagree, which text you used.
- **"Carried forward from the <story> reviews":** what later phases or "Before production" must do.
- **New open questions:** add them to the table with the next number, the stories involved and what they block.

If the story added a package, a dependency, a fixture or a pattern other code must follow, add it to `CLAUDE.md`'s Architecture section.

## 7. Report

Tell the user:
- what's built, as a table of endpoints and what each does;
- the decisions that matter;
- what the reviews found and how it was fixed;
- the new questions for the BA;
- what isn't done or verified.

Don't commit unless the user asks.
