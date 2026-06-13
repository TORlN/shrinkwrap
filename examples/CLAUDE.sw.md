## Security Rules

Never commit secrets, API keys, or credentials to the repository under any circumstances.
Never use eval() or exec() with user-supplied input.
Always validate and sanitize all input at system boundaries before processing.
Forbidden: storing plaintext passwords. Use bcrypt with a cost factor of at least 12.
Must not use MD5 or SHA1 for cryptographic purposes. Use SHA-256 or better.
Do not disable SSL/TLS certificate verification in any environment, including development.
Never log sensitive user data (passwords, tokens, PII) even at debug level.

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
- tests are passing on main
- staging deploy is up to date
- deploy pipeline is green

## Recent Decisions

- Chose Resend over SendGrid for transactional email (better DX, simpler pricing)
- Decided to defer WebSocket support to Q3 — SSE is sufficient for current use cases
- Will use Stripe for payments; Paddle was ruled out due to EU tax complexity

## Open Questions

- Should the notification system fan out synchronously or via the message bus?
- Do we need row-level security in Postgres now, or can that wait until multi-tenancy?
- What's the retention policy for audit logs? Legal hasn't confirmed yet.

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
- Run `make test` to execute the full test suite (unit + integration)

