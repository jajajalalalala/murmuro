# AGENTS.md — Handover guide for AI coding agents

> If you are an AI agent (Claude, GPT, Cursor, Copilot, etc.) working on Murmuro, **read this file first**. It tells you how to pick up where the previous session left off and how to ship changes that the maintainer will accept without rework.

## What Murmuro is

A minimal, local-first push-to-talk dictation tool for macOS and Windows. One job: hold a hotkey → speak → text appears.

The product vision and milestone-by-milestone roadmap live in [ROADMAP.md](ROADMAP.md). Treat it as the source of truth for what is shipped, what is in progress, and what is explicitly *not* being built.

## Where to look first (in order)

1. **[ROADMAP.md](ROADMAP.md)** — current milestone and the next checkbox to tick.
2. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — module map, data flow, state machine, cross-platform notes.
3. **[CONTRIBUTING.md](CONTRIBUTING.md)** — branch / PR / test rules. **You must follow these.**
4. **`git log --oneline -20`** — what just happened. The last commit's tree is the most current shape of the code.
5. **Open PRs and issues** on GitHub — what is in flight that you should not duplicate.

## Hard rules for AI agents

These are not suggestions. They are the contract.

### 1. Branch + PR for every change
- Never commit directly to `main`.
- One feature / fix = one branch = one PR. Keep PRs small enough that a human can review them in five minutes.
- Branch naming: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`, `refactor/<slug>`.
- Commit messages: imperative mood, one-line subject, explain *why* in the body if non-obvious.

### 2. Tests must pass before merge
- `pytest -q` must be green.
- `ruff check src tests` must be clean.
- CI runs both on every push. Do not merge a PR with a red check.

### 3. Update the roadmap when you ship
- When a milestone checkbox is satisfied, tick it in [ROADMAP.md](ROADMAP.md) **in the same PR**.
- If you add scope to a milestone, add a checkbox.
- If you discover something out of scope, add it to the v1.1+ backlog — do not silently expand the current milestone.

### 4. Don't break the install path
- `./start.sh` must produce a working app on macOS without any system-level setup beyond what's already documented in the README.
- If you add a new system dependency, document it in `start.sh` and the README in the same PR.

### 5. Local-first stays local-first
- Never make the OpenAI backend the default. The product promise is: works offline.
- Never add telemetry, analytics, or any network call outside the optional cloud transcription backend.

### 6. No premature features
- The roadmap deliberately defers features (AI rewrite, history viewer, custom vocabulary). Do not implement them unless the maintainer has moved them into the current milestone.
- See the **Principles** section at the bottom of [ROADMAP.md](ROADMAP.md).

## Workflow you should run for any change

```bash
# 1. Sync
git checkout main && git pull

# 2. Branch
git checkout -b feat/my-thing

# 3. Work, commit small steps
# ... edit files ...
git add -p && git commit -m "feat: meaningful imperative summary"

# 4. Local checks (mirror CI)
./start.sh --setup-only            # ensures venv + deps still install cleanly
.venv/bin/pytest -q
.venv/bin/ruff check src tests

# 5. Push and open PR
git push -u origin feat/my-thing
# Open PR via gh or the GitHub web UI; PR template will be pre-filled.

# 6. After CI passes and the PR is reviewed, squash-merge into main.
```

## Handover checklist (when ending a session)

When you stop work mid-task, leave the next agent (or future-you) a fighting chance:

- [ ] All work-in-progress is on a branch (not on `main`, not uncommitted).
- [ ] If the branch is incomplete, the PR is opened as a **draft** with a checklist of what remains in the body.
- [ ] [ROADMAP.md](ROADMAP.md) reflects what shipped vs. what's still open.
- [ ] Any non-obvious decision made during the session is captured in the PR description or in a code comment near the affected code (not just in chat).
- [ ] If you discovered something the maintainer needs to decide, file a GitHub issue rather than guessing.

## Things that are *not* your call

Don't make these decisions yourself. Surface them and let the human decide:

- Adding a paid/cloud-only dependency.
- Changing the default backend, default hotkey, or product positioning.
- Renaming the project.
- Adding telemetry of any kind.
- Removing items from [ROADMAP.md](ROADMAP.md) (only the maintainer prunes scope).
