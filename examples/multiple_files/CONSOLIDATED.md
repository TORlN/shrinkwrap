## Security Rules

Never commit secrets, API keys, or credentials to the repository under any circumstances.
Never use eval() or exec() with user-supplied input.
Always validate and sanitize all input at system boundaries before processing.
Never log sensitive user data (passwords, tokens, PII) even at debug level.

## Code Style

- Use `ruff` for linting and formatting — run `ruff check . --fix && ruff format .` before committing
- Type hints are mandatory on all public functions and class methods
- Maximum line length is 100 characters
- Prefer `pathlib.Path` over `os.path` for all filesystem operations
- f-strings over `.format()` or `%` formatting everywhere
- No `print()` in production code — use the `logging` module or `rich.console`

## Cursor Workflow

- Always read the file before editing — never assume the current state from memory
- Prefer editing existing files over creating new ones
- When writing tests, follow the existing test file naming convention (`test_<module>.py`)
- Run the test suite after every non-trivial change: `make test`
- Do not leave TODO comments in committed code — convert them to GitHub issues instead
- tests are passing on main
- staging deploy is up to date
- deploy pipeline is green

## Pull Request Guidelines

- PRs must have a description that explains the *why*, not just the *what*
- Link to the relevant Linear ticket in the PR description
- All PRs require at least one approval before merging
- Squash merge only — no merge commits on main
- Delete the branch after merging

## Agent Behaviour

This file defines how AI coding agents should operate in this repository.
These rules apply to Claude Code, Cursor, Copilot, and any other AI pair-programming tools.

- Always read a file before editing it — never assume its current contents
- Never make changes outside the scope of the current task
- Prefer the smallest diff that accomplishes the goal
- Do not refactor code that is unrelated to the current task
- When uncertain about intent, ask rather than guess

## Testing Conventions

- Unit tests live in `tests/` and mirror the source tree structure
- Use `pytest` with fixtures defined in `conftest.py` — do not create new fixture files
- Every new public function must have at least one test
- Mock at the boundary (external HTTP calls, database, filesystem) — not inside the module
- Test names follow the pattern `test_<behaviour>_<condition>`
- Run `make test` to execute the full test suite (unit + integration)

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

## Architecture Decisions

- Monorepo structure: all services under `services/`, shared libs under `packages/`
- API layer uses FastAPI with async handlers throughout; no sync route handlers
- PostgreSQL is the primary datastore; Redis for caching and rate limiting only
- All inter-service communication goes through the internal message bus (RabbitMQ)
- Authentication: JWT access tokens (15 min TTL) + refresh tokens (7 day TTL) in httpOnly cookies
- Database migrations managed by Alembic; never modify migration files after they are merged
- Frontend is Next.js 14 with App Router; no Pages Router code to be added
- Deployment target is Kubernetes on GCP; Helm charts live in `infra/helm/`

## Current Sprint

- Working on: OAuth2 social login (Google, GitHub)
- Working on: email verification flow for new signups
- Working on: admin dashboard — user management table
- In review: rate limiting middleware (PR #214)
- In review: password reset flow (PR #208)
- Blocked: S3 presigned URL uploads — waiting on DevOps to provision the bucket

## Todo / Backlog

1. Add OpenTelemetry tracing to all FastAPI routes
2. Write integration tests for the OAuth2 flow
3. Set up Sentry for error tracking in production
4. Implement soft-delete for user accounts
5. Add CSV export to the admin dashboard
6. Document the internal message bus contract in the wiki
7. Migrate legacy `user_sessions` table to the new token schema
8. Performance audit on the search endpoint (currently p99 > 2s)

## Environment & Tooling

- Python 3.12, managed via `pyenv`; see `.python-version` at repo root
- Node 20 LTS for the frontend; use `nvm use` in the `frontend/` directory
- Pre-commit hooks are mandatory: `pre-commit install` after cloning
- Run `make dev` to start all services locally on default ports
- API docs available at `http://localhost:8000/docs` when the backend is running
