# Known Issues

## Architecture
- `app/main.py` is very large (~300KB) and mixes routing, business logic, DB bootstrap/migrations, storage, and reporting.
- Router modularization is incomplete: `app/routers/multitenant.py` exists but mount is commented in `app/main.py`.
- DB abstraction logic is duplicated between `app/main.py` and `app/db.py`.

## Security
- `APP_SECRET` has a permissive default fallback (`dev-secret-change-me`) instead of hard fail in non-dev.
- Diagnostic schema endpoint (`/diag/schema`) exposes internals and should be restricted.
- Attachment serving relies on DB `stored_filepath`; path allowlisting can be tightened.
- Logging includes sensitive operational details and SMTP fallback may print email content.

## Database
- Runtime schema changes (`CREATE TABLE`, `ALTER TABLE`) are embedded in app startup logic.
- Formal migrations exist but are mixed with runtime DDL, increasing drift risk.
- SQLite/PostgreSQL compatibility wrapper introduces dual-path complexity and backend parity risk.
- Widespread `table_has_column(...)` checks indicate multiple schema states in active execution paths.

## Maintainability
- Heavy inline SQL across route handlers makes changes high risk and harder to test.
- Complex handler functions combine validation, persistence, IO, and response composition.
- Org/membership logic is spread across `main.py`, `dependencies.py`, and `models.py`.

## Testing
- Existing tests are mostly script-style endpoint calls, not comprehensive pytest suites with strong assertions.
- Limited evidence of automated coverage for authz isolation, migration regressions, and SQLite/Postgres parity.

## Observability
- Logging is mostly unstructured `print(...)` statements.
- `/health` is a shallow liveness check and does not validate dependencies.
- No clear metrics/tracing instrumentation baseline.
