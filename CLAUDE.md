# Timer 2.0 Claude Instructions

## Project goal
Timer 2.0 is a production-quality surgical procedure timer inspired by the old Django Timer project. Priorities are correctness, debuggability, clean domain modeling, auditability, and simple deployment.

## Development rules
- Prefer small, incremental changes.
- Before large edits, explain the plan and expected files to change.
- Do not introduce Kubernetes before the app works locally and in Docker Compose.
- Do not store secrets in code.
- Use environment variables for configuration.
- Log to stdout/stderr.
- Add or update tests for meaningful behavior changes.

## Backend
- Use Django and Django REST Framework.
- Use PostgreSQL as the primary database.
- Keep business logic out of views where practical.
- Prefer service functions or model methods for timer state transitions.

## Core domain
- Surgeon represents a person who performs operations.
- OperationType defines a reusable surgical procedure type.
- Step defines a named, globally reusable operation milestone.
- OperationInstance represents one performed procedure.
- StepInstance records start/end/duration for a step within an operation.
- Audit events are not stored in the database. They are emitted to stdout
  as structured JSON via the `timer.audit` logger and collected by the log
  aggregation layer (Loki/Grafana, configured in Milestone 6).

## Commands
- Run tests: `pytest`
- Run Django checks: `python manage.py check`
- Run migrations: `python manage.py migrate`
- Start local stack: `docker compose up --build`

## Debugging rules
- When a test or command fails, diagnose before editing.
- Prefer the smallest fix that explains the observed failure.
- After a fix, rerun the failing command.
