# Contributing to Murmuro

Murmuro is a personal tool, but it follows a real engineering workflow so that anyone (human or AI agent) can pick it up months from now and ship a change without breaking anything.

## TL;DR

```
main is protected. Every change goes through:
  branch → commits → push → PR → green CI → squash-merge → delete branch
```

## Workflow

### 1. Start from a clean main

```bash
git checkout main
git pull --ff-only
```

### 2. Create a topic branch

Name it by intent:

| Prefix       | Use for                              | Example                            |
|--------------|--------------------------------------|------------------------------------|
| `feat/`      | New user-visible feature             | `feat/auto-paste`                  |
| `fix/`       | Bug fix                              | `fix/start-sh-venv-mismatch`       |
| `chore/`     | Tooling, CI, deps, repo plumbing     | `chore/contributor-workflow`       |
| `docs/`      | Documentation only                   | `docs/macos-permissions`           |
| `refactor/`  | Internal change, no behavior change  | `refactor/extract-state-machine`   |

```bash
git checkout -b feat/my-thing
```

### 3. Commit in small, reviewable steps

- Imperative subject line under 70 chars: `feat: add waveform indicator to tray icon`.
- One logical change per commit when possible.
- If you are fixing a typo or formatting in your own PR before merge, use `--amend` or `--fixup`.

### 4. Run the local checks before pushing

These mirror what CI does. Don't push until they pass.

```bash
./start.sh --setup-only            # confirms install still works end-to-end
.venv/bin/pytest -q                # unit tests
.venv/bin/ruff check src tests     # lint
```

### 5. Push and open a PR

```bash
git push -u origin feat/my-thing
```

Then open a PR against `main`. The [PR template](.github/PULL_REQUEST_TEMPLATE.md) will pre-fill the description — fill in every section.

### 6. Wait for CI, then merge

- Required: the **CI** workflow must be green.
- Use **squash and merge**. The PR title becomes the commit message on `main`, so make it good.
- Delete the branch after merge.

### 7. Update the roadmap *in the same PR*

If your change ticks a checkbox in [ROADMAP.md](ROADMAP.md), tick it. If it adds scope, add a checkbox. The roadmap is the living spec.

## What to test

- **Unit-testable things** (config, state machine, audio buffer math): cover with `pytest`.
- **Hardware/permission things** (mic capture, global hotkeys, paste): smoke-test manually on macOS and document in the PR description what you tried.

## Code style

- Python 3.10+ syntax (we pin 3.11 at runtime, but support 3.10 for type-hint use).
- `ruff` enforces formatting and lint. Run `ruff check --fix` before committing.
- No trailing whitespace, no debug prints in committed code.
- Prefer explicit imports over `*`.
- Public modules go in `src/murmuro/`, tests in `tests/`. Mirror the source path.

## Dependencies

Adding a runtime dependency is a real cost (install time, install failures, audit surface). Only add one when:

1. There is no reasonable stdlib path.
2. The library is actively maintained.
3. You document *why* in the PR description.

Pin in `pyproject.toml` with a sensible lower bound; do not pin upper bounds unless a known breaking change forces it.

## Reporting bugs

Open an issue with:

- macOS / Windows version
- Python version (`.venv/bin/python --version`)
- Output of `murmuro --show-config`
- Steps to reproduce, expected vs. actual

## License

By contributing you agree that your contributions are licensed under the MIT License covering this repo.
