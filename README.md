# Codex-Optimized Side Project Starter

A small starter template for using OpenAI Codex effectively on side projects while keeping token usage under control.

## Goals

- Keep project context small and stable
- Make Codex prompts shorter and more reliable
- Encourage safe, incremental edits
- Reduce repeated explanations across threads

## Project layout

```text
.
├── AGENTS.md
├── README.md
├── PROJECT_STATE.md
├── TASKS.md
├── PROMPTS.md
├── .gitignore
├── .env.example
├── .vscode/
│   └── settings.json
├── docs/
│   └── architecture.md
├── src/
│   └── main.py
└── tests/
    └── test_smoke.py
```

## How to use this with Codex

1. Open this repo in the Codex app or your IDE with Codex enabled.
2. Start by asking Codex to read only:
   - `README.md`
   - `AGENTS.md`
   - `PROJECT_STATE.md`
   - the one file you want changed
3. Use small tasks:
   - “Plan only. No code yet.”
   - “Modify only `src/main.py`.”
   - “Show a minimal diff and explain the change.”
4. Before bigger tasks, commit a checkpoint:
   ```bash
   git init
   git add .
   git commit -m "Initial Codex starter"
   ```
5. After each successful milestone, update `PROJECT_STATE.md`.

## Recommended workflow

- **Step 1:** Ask for a plan
- **Step 2:** Approve one step
- **Step 3:** Ask for tests or validation
- **Step 4:** Commit
- **Step 5:** Start a fresh thread for the next task if context is getting noisy

## Example prompts

See `PROMPTS.md` for copy/paste examples.
