# Milestone 4 — Implementation Notes

Deviations from the original plan, unexpected problems, and how they were
resolved. Each entry is written verbosely so the reasoning is clear on review.

---

- **`docker compose` plugin was not installed alongside Docker Engine (Step 6)**

  Running `docker compose up --build -d` produced `unknown flag: --build` rather
  than the expected build output. This error occurs because Docker Engine on
  Ubuntu/WSL does not automatically include the Compose v2 plugin — it is a
  separate package (`docker-compose-plugin`) that must be installed from the
  official Docker apt repository.

  The official Docker apt repository was also not present on the system, so
  `apt-get install docker-compose-plugin` failed with "package not found". The
  fix required three steps:

  1. Add Docker's GPG signing key to `/etc/apt/keyrings/docker.gpg`
  2. Write the official Docker apt source to `/etc/apt/sources.list.d/docker.list`
  3. Run `sudo apt-get update && sudo apt-get install -y docker-compose-plugin`

  A secondary issue arose during step 2: the `echo` command with shell line
  continuations (`\`) split the apt source URL across two lines in the file,
  producing a malformed URL that caused `apt-get update` to fail. The fix was
  to write the entire source as a single unbroken line:

  ```
  deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable
  ```

  **Takeaway:** On a fresh Ubuntu/WSL machine, Docker Engine and the Compose
  plugin must be installed separately from the official Docker apt repository.
  The Docker Desktop installer (macOS/Windows) bundles both together, which is
  why this step is often taken for granted.

- **`DATABASE_URL` must differ between local dev and Docker Compose (Step 6)**

  The `.env` file is shared between two contexts that need different database
  hostnames:

  - **Local dev / pytest** — Django runs on the host machine; Postgres is also
    on the host; `DATABASE_URL` must use `@localhost:5432`.
  - **Docker Compose** — Django runs inside the `backend` container; Postgres
    runs inside the `db` container on the same Compose network; `DATABASE_URL`
    must use `@db:5432` (the service name, not `localhost`).

  The `docker-compose.yml` uses `env_file: ./backend/.env`, so there is only
  one `.env` file serving both contexts. When switching between them the
  `DATABASE_URL` host must be updated manually.

  For this smoke test, `.env` was temporarily updated to `@db:` before running
  `docker compose up --build`, then reverted to `@localhost:` afterward so
  `pytest` continued to work.

  **Longer-term options** (not implemented yet, noted here for Milestone 4+):
  - Use a separate `backend/.env.docker` for Compose and point `env_file` at
    it, keeping `.env` for local dev.
  - Use Compose's `environment:` block to override just `DATABASE_URL` at the
    service level, leaving `.env` untouched.
  - Use Docker Compose profiles so developers explicitly choose a context.
