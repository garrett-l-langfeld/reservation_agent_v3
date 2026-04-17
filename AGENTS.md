# Agent instructions for this repository

Follow these rules unless the user explicitly overrides them.

## Primary objective

Make small, high-confidence changes with minimal token usage and minimal disruption.

## Working style

1. Read only the files needed for the current task.
2. Prefer proposing a short plan before making edits.
3. Change only the files explicitly named by the user unless another file is strictly necessary.
4. Do not refactor unrelated code.
5. Do not rewrite files for style alone.
6. Do not print unchanged code.
7. Prefer minimal diffs.
8. When uncertain, ask for or identify the smallest missing piece of context.
9. Preserve existing naming unless there is a clear bug or inconsistency.
10. Explain assumptions briefly.

## Output preferences

- Summarize what changed in 3-6 bullets max.
- If you edited code, mention:
  - files changed
  - why
  - how to test
- Prefer diffs or changed sections over full-file dumps.

## Coding preferences

- Keep modules small and focused.
- Add or update tests for non-trivial logic changes.
- Use clear names over clever abstractions.
- Avoid adding dependencies unless justified.
- Favor readability and maintainability for a non-fulltime developer.

## Safety rails

- Never delete large sections without explaining why.
- Never introduce secrets into source control.
- Flag risky migrations or irreversible changes before making them.

## Cost control

- Prefer local reasoning over broad repo scans.
- If the task is large, break it into phases and complete one phase at a time.
- Reuse repository docs instead of asking the user to restate project context.
