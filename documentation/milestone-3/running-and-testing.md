# Milestone 3 — Running and Testing

This guide covers everything needed to set up, run, and manually verify the
Milestone 3 deliverables: JWT authentication, per-user data isolation, audit
logging, and the Django Admin surgeon/user account workflow.

---

## Prerequisites

Milestones 1 and 2 must be complete: Django project configured, PostgreSQL
running, migrations applied, and the virtual environment ready. See the
earlier running-and-testing guides for setup instructions.

### Apply new migrations

Milestone 3 adds two sets of migrations: one for the `user` field on `Surgeon`
and one for the SimpleJWT token blacklist tables.

```bash
cd timer-2.0/backend
.venv/bin/python manage.py migrate
```

Expected output includes:

```
Applying timer.0002_surgeon_user... OK
Applying token_blacklist.0001_initial... OK
...
Applying token_blacklist.0013_alter_blacklistedtoken_options_and_more... OK
```

---

## Automated Tests

Run the full pytest suite (72 tests: 51 from M2, 21 new in M3):

```bash
cd timer-2.0/backend
.venv/bin/pytest -v
```

Expected output:

```
timer/tests/test_api.py .....................  [ 43%]   (51 tests)
timer/tests/test_auth.py .....................  [100%]  (21 tests)

======================= 72 passed in x.xxs ========================
```

---

## Manual Tests

All tests below assume the server is running:

```bash
cd timer-2.0/backend
.venv/bin/python manage.py runserver
```

Create a superuser if you haven't already:

```bash
.venv/bin/python manage.py createsuperuser
```

---

### 1. Health endpoint remains open

Confirm the health endpoint does not require a token:

```bash
curl -s http://localhost:8000/health/
```

Expected: `{"status": "ok"}` with HTTP 200. No `Authorization` header needed.

---

### 2. Protected endpoints reject unauthenticated requests

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/surgeons/
```

Expected: `401`

```bash
curl -s http://localhost:8000/api/v1/surgeons/
```

Expected JSON body:

```json
{"detail": "Authentication credentials were not provided."}
```

---

### 3. Create a surgeon account via Django Admin

JWT authentication requires a `User` linked to a `Surgeon`. The only supported
path is through the Django Admin — there is no self-registration.

1. Start the server and visit `http://localhost:8000/admin/`.
2. Log in with your superuser credentials.
3. Navigate to **Authentication and Authorization → Users → Add User**.
4. Fill in a username and password (e.g. `drsmith` / `password`).
5. After saving, scroll down to the **Surgeon profile** inline section.
6. Fill in first name, last name, and email, then save.

The surgeon is now linked to the login account. Confirm by visiting
**Timer → Surgeons** — the surgeon should appear with the username shown in
the **Login account** column.

---

### 4. Login

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "drsmith", "password": "password"}'
```

Expected: HTTP 200 with both tokens:

```json
{
  "access": "eyJ...",
  "refresh": "eyJ..."
}
```

Save the tokens to shell variables for the tests below:

```bash
ACCESS=$(curl -s -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "drsmith", "password": "password"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['access'])")

REFRESH=$(curl -s -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "drsmith", "password": "password"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['refresh'])")
```

---

### 5. Failed login emits audit log

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "drsmith", "password": "wrongpassword"}'
```

Expected: HTTP 401.

In the server terminal, look for a JSON log line from `timer.audit` at
`WARNING` level:

```json
{"timestamp": "...", "level": "WARNING", "logger": "timer.audit",
 "message": "login_failure", "username": "drsmith", "ip": "127.0.0.1"}
```

---

### 6. Use the access token to call a protected endpoint

```bash
curl -s http://localhost:8000/api/v1/surgeons/ \
  -H "Authorization: Bearer $ACCESS"
```

Expected: HTTP 200 with paginated results.

---

### 7. Token refresh

Access tokens expire after 15 minutes. Obtain a new one using the refresh token:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refresh\": \"$REFRESH\"}"
```

Expected: HTTP 200 with a new `access` token (and a new `refresh` token, since
rotation is enabled).

---

### 8. Logout

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/logout/ \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d "{\"refresh\": \"$REFRESH\"}"
```

Expected: HTTP 204 (no response body).

In the server terminal, look for a `timer.audit` INFO line:

```json
{"timestamp": "...", "level": "INFO", "logger": "timer.audit",
 "message": "logout", "user_id": 2, "ip": "127.0.0.1"}
```

---

### 9. Blacklisted token is rejected

After logging out, the refresh token is blacklisted. Attempting to use it again
should fail:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refresh\": \"$REFRESH\"}"
```

Expected: HTTP 401.

---

### 10. Per-user data isolation

Create a second surgeon account via the Admin (e.g. `drjones`). Log in as
`drjones` and create an operation instance via the API.

Now log in as `drsmith` and list operation instances:

```bash
ACCESS_SMITH=$(curl -s -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "drsmith", "password": "password"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access'])")

curl -s http://localhost:8000/api/v1/operation-instances/ \
  -H "Authorization: Bearer $ACCESS_SMITH"
```

Expected: `"count": 0` — Dr. Smith cannot see Dr. Jones's operations.

---

### 11. Admin sees all data

Log in as the superuser and list operation instances:

```bash
ACCESS_ADMIN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-superuser-password>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access'])")

curl -s http://localhost:8000/api/v1/operation-instances/ \
  -H "Authorization: Bearer $ACCESS_ADMIN"
```

Expected: all operations across all surgeons are returned.

---

### 12. Standard user cannot write reference data

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-types/ \
  -H "Authorization: Bearer $ACCESS_SMITH" \
  -H "Content-Type: application/json" \
  -d '{"operation_type": "Hip Replacement"}'
```

Expected: HTTP 403.

---

### 13. Audit log — operation create

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-instances/ \
  -H "Authorization: Bearer $ACCESS_SMITH" \
  -H "Content-Type: application/json" \
  -d '{"surgeon": 1, "operation_type": 1, "date": "2024-06-01"}'
```

Expected: HTTP 201. In the server terminal:

```json
{"timestamp": "...", "level": "INFO", "logger": "timer.audit",
 "message": "operation_create", "user_id": 2, "operation_instance_id": 1,
 "surgeon_id": 1, "operation_type": "Knee Replacement"}
```

---

## Summary Checklist

| # | Test | Pass condition |
|---|---|---|
| 1 | `GET /health/` unauthenticated | 200, `{"status": "ok"}` |
| 2 | `GET /api/v1/surgeons/` unauthenticated | 401 |
| 3 | Create surgeon via Admin | Surgeon appears with linked username in list |
| 4 | Login with valid credentials | 200, `access` and `refresh` tokens returned |
| 5 | Login with wrong password | 401, `login_failure` in `timer.audit` log |
| 6 | Authenticated request with access token | 200 |
| 7 | Token refresh | 200, new `access` token returned |
| 8 | Logout | 204, `logout` event in `timer.audit` log |
| 9 | Refresh with blacklisted token | 401 |
| 10 | Surgeon sees only own operations | `count: 0` for other surgeon's data |
| 11 | Admin sees all operations | All records returned |
| 12 | Standard user write to reference data | 403 |
| 13 | Operation create emits audit log | `operation_create` event with `user_id` |
| 14 | Automated tests | All 72 pass with no unexpected warnings |
