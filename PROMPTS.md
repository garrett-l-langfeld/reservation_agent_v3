# Prompt snippets for Codex

These are designed to reduce context size and keep the agent focused.

## 1) Planning only

Read `README.md`, `AGENTS.md`, and `PROJECT_STATE.md`, then review only `src/main.py`.
Propose a short plan to implement [FEATURE].
Do not write code yet.
Do not inspect unrelated files.

## 2) Minimal implementation

Read `README.md`, `AGENTS.md`, and `PROJECT_STATE.md`.
Modify only `src/main.py` to implement [FEATURE].
Keep the diff minimal.
Do not refactor unrelated code.
At the end, summarize the change and how to test it.

## 3) Debugging

Read `README.md`, `AGENTS.md`, and `PROJECT_STATE.md`.
Focus only on `src/main.py` and `tests/test_smoke.py`.
Investigate why [ERROR] happens.
Explain the root cause first, then make the smallest reliable fix.

## 4) Adding tests

Read `README.md`, `AGENTS.md`, and `PROJECT_STATE.md`.
Add tests only in `tests/test_smoke.py` for the behavior in `src/main.py`.
Do not change application code unless a tiny fix is required for testability.

## 5) Safe refactor

Read `README.md`, `AGENTS.md`, and `PROJECT_STATE.md`.
Refactor only `src/main.py` for readability.
Preserve behavior.
Avoid introducing new dependencies.
Show a concise summary of what changed.

## 6) Fresh thread handoff

Read `README.md`, `AGENTS.md`, and `PROJECT_STATE.md`.
Based on that context, help me continue the project from its current state.
First list the 3 most logical next steps, then wait for me to choose one.
