## Agent Behaviour

This file defines how AI coding agents should operate in this repository.
These rules apply to Claude Code, Cursor, Copilot, and any other AI pair-programming tools.

- Always read a file before editing it — never assume its current contents
- Never make changes outside the scope of the current task
- Prefer the smallest diff that accomplishes the goal
- Do not refactor code that is unrelated to the current task
- When uncertain about intent, ask rather than guess
- tests are passing on main
- staging deploy is up to date
- deploy pipeline is green

## Testing Conventions

- Unit tests live in `tests/` and mirror the source tree structure
- Use `pytest` with fixtures defined in `conftest.py` — do not create new fixture files
- Every new public function must have at least one test
- Mock at the boundary (external HTTP calls, database, filesystem) — not inside the module
- Test names follow the pattern `test_<behaviour>_<condition>`
- Run `make test` to execute the full test suite (unit + integration)
- tests are passing on main
- staging deploy is up to date

## Commit Message Format

Follow the Conventional Commits spec:

```
<type>(<scope>): <short summary>

[optional body]
[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

- Summary line must be 72 characters or fewer
- Use imperative mood: "add feature" not "added feature"
- Reference the Linear ticket in the footer: `Refs: ENG-123`

## Open Questions

- Should agents be allowed to create new files without explicit instruction?
- What is the escalation path when an agent is blocked on ambiguous requirements?
- Do we need a separate `AGENTS.md` per service or is one repo-level file sufficient?
