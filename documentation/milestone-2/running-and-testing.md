# Milestone 2 — Running and Testing

This guide covers everything needed to set up, run, and manually verify the
Milestone 2 deliverables: the DRF REST API layer, request-logging middleware,
service functions, and the automated pytest suite.

---

## Prerequisites

Milestone 1 must be complete: Django project configured, PostgreSQL running,
migrations applied, and the virtual environment ready. See
`documentation/milestone-1/running-and-testing.md` for setup instructions.

### Additional dependencies

Milestone 2 adds two packages. Confirm they are installed:

```bash
cd timer-2.0/backend
.venv/bin/pip list | grep -E "djangorestframework|django-filter"
```

Expected output:

```
django-filter          25.x.x
djangorestframework    3.x.x
```

---

## Running the Development Server

```bash
cd timer-2.0/backend
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

The server is available at `http://localhost:8000`. With `DEBUG=True`, the
DRF browsable API is also available at any `/api/v1/` URL in a browser.

---

## Automated Tests

Run the full pytest suite (51 tests):

```bash
cd timer-2.0/backend
.venv/bin/pytest -v
```

Expected output:

```
collected 51 items

timer/tests/test_api.py ......................             [ 43%]
timer/tests/test_serializers.py .........                 [ 60%]
timer/tests/test_services.py ....................          [100%]

======================= 51 passed in x.xxs ========================
```

All 51 tests must pass. The only acceptable warning is about the missing
`static_files/` directory (produced by `collectstatic`, not needed for tests).

---

## Manual Tests

All tests below assume the server is running. Create a superuser first if you
haven't already:

```bash
.venv/bin/python manage.py createsuperuser
```

---

### 1. API root

```bash
curl -s http://localhost:8000/api/v1/ | python3 -m json.tool
```

Expected: a JSON object listing the five resource URLs (`surgeons`,
`operation-types`, `steps`, `step-instances`, `operation-instances`).

---

### 2. Surgeon CRUD

**Create:**

```bash
curl -s -X POST http://localhost:8000/api/v1/surgeons/ \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Jane", "last_name": "Smith", "email": "jane@example.com"}'
```

Expected: HTTP 201 with a JSON body including `"full_name": "Jane Smith"`.

**List:**

```bash
curl -s http://localhost:8000/api/v1/surgeons/
```

Expected: paginated JSON with `count`, `results` array containing the created surgeon.

**Retrieve:**

```bash
curl -s http://localhost:8000/api/v1/surgeons/1/
```

Expected: surgeon detail including `full_name`.

**Partial update:**

```bash
curl -s -X PATCH http://localhost:8000/api/v1/surgeons/1/ \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Janet"}'
```

Expected: HTTP 200, `first_name` updated.

---

### 3. OperationType and Step

**Create an operation type:**

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-types/ \
  -H "Content-Type: application/json" \
  -d '{"operation_type": "Knee Replacement"}'
```

Expected: HTTP 201.

**Create two steps:**

```bash
curl -s -X POST http://localhost:8000/api/v1/steps/ \
  -H "Content-Type: application/json" \
  -d '{"title": "Incision"}'

curl -s -X POST http://localhost:8000/api/v1/steps/ \
  -H "Content-Type: application/json" \
  -d '{"title": "Closure"}'
```

Expected: HTTP 201 for each.

---

### 4. OperationInstance — list and create

**Create an operation (use IDs from the objects created above):**

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-instances/ \
  -H "Content-Type: application/json" \
  -d '{"surgeon": 1, "operation_type": 1, "date": "2024-06-01", "in_room_time": "08:00:00"}'
```

Expected: HTTP 201, `"complete": false`, no `steps` key in the response
(the list serializer is flat).

**List:**

```bash
curl -s http://localhost:8000/api/v1/operation-instances/
```

Expected: paginated results. Confirm `steps` is **not** present in list results.

---

### 5. OperationInstance — retrieve with nested steps

Add step instances, then retrieve:

```bash
curl -s -X POST http://localhost:8000/api/v1/step-instances/ \
  -H "Content-Type: application/json" \
  -d '{"step": 1, "operation_instance": 1, "order": 0, "end_time": "08:30:00"}'

curl -s -X POST http://localhost:8000/api/v1/step-instances/ \
  -H "Content-Type: application/json" \
  -d '{"step": 2, "operation_instance": 1, "order": 1, "end_time": "09:00:00"}'

curl -s http://localhost:8000/api/v1/operation-instances/1/
```

Expected: detail response includes a `steps` array with two entries, each
containing `step_title`, `start_time`, `end_time`, `elapsed_time`, and
`dist_from_average`.

---

### 6. suggested-steps

**With no history** (a brand-new operation for a surgeon who has no completed
operations of this type):

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-instances/ \
  -H "Content-Type: application/json" \
  -d '{"surgeon": 1, "operation_type": 1, "date": "2024-07-01"}'

curl -s http://localhost:8000/api/v1/operation-instances/2/suggested-steps/
```

Expected: `[]`

**With history** (after completing operation 1 below):

```bash
curl -s http://localhost:8000/api/v1/operation-instances/2/suggested-steps/
```

Expected: `[{"id": 1, "title": "Incision"}, {"id": 2, "title": "Closure"}]`
(or the same steps in order from the completed reference operation).

---

### 7. complete action — success

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-instances/1/complete/
```

Expected: HTTP 200. The response body is the full detail serializer including:

```json
{
  "complete": true,
  "elapsed_time": 3600,
  "steps": [
    {"step_title": "Incision", "start_time": "08:00:00", "end_time": "08:30:00", "elapsed_time": 1800, ...},
    {"step_title": "Closure",  "start_time": "08:30:00", "end_time": "09:00:00", "elapsed_time": 1800, ...}
  ]
}
```

`in_room_time` becomes `start_time` for the first step; each step's `end_time`
becomes `start_time` for the next.

---

### 8. complete action — validation errors

**Already complete:**

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-instances/1/complete/
```

Expected: HTTP 400, `{"detail": "Operation is already complete."}`.

**Missing in_room_time:**

```bash
curl -s -X POST http://localhost:8000/api/v1/operation-instances/ \
  -H "Content-Type: application/json" \
  -d '{"surgeon": 1, "operation_type": 1, "date": "2024-08-01"}'

# Add a step instance with an end_time
curl -s -X POST http://localhost:8000/api/v1/step-instances/ \
  -H "Content-Type: application/json" \
  -d '{"step": 1, "operation_instance": 3, "order": 0, "end_time": "08:30:00"}'

curl -s -X POST http://localhost:8000/api/v1/operation-instances/3/complete/
```

Expected: HTTP 400, `{"detail": "Operation has not been started (in_room_time is not set)."}`.

---

### 9. export-csv

```bash
curl -s http://localhost:8000/api/v1/operation-instances/1/export-csv/ -o export.csv
head -2 export.csv
```

Expected first line (CSV headers):

```
Step,Start Time,End Time,Elapsed Time (s),Dist from Average (%)
```

Subsequent lines contain one row per step. `Dist from Average (%)` will show
`N/A` until the surgeon has historical data for comparison.

Also confirm the `Content-Disposition` header carries the correct filename:

```bash
curl -sI http://localhost:8000/api/v1/operation-instances/1/export-csv/ \
  | grep -i content-disposition
```

Expected: `Content-Disposition: attachment; filename="Knee Replacement_2024-06-01.csv"`

---

### 10. Request logging middleware

Start the server with `LOG_LEVEL=DEBUG` and make any API request:

```bash
LOG_LEVEL=DEBUG .venv/bin/python manage.py runserver
```

In a second terminal:

```bash
curl -s http://localhost:8000/api/v1/surgeons/
```

In the server terminal, look for a JSON log line from the `timer.api` logger:

```json
{"timestamp": "...", "level": "INFO", "logger": "timer.api", "message": "request",
 "method": "GET", "path": "/api/v1/surgeons/", "status": 200, "duration_ms": 5}
```

Confirm:
- `method`, `path`, `status`, and `duration_ms` are all present
- 4xx responses log at `WARNING`; 5xx responses log at `ERROR`

---

### 11. dist_from_average after completing two operations

With operation 1 already complete, create and complete a second identical
operation and then retrieve its step instances:

```bash
curl -s http://localhost:8000/api/v1/operation-instances/2/
```

After completing operation 2, `dist_from_average` on each step should be a
float percentage comparing the step's elapsed time to the surgeon's average
from operation 1. A value of `0.0` means exactly on average.

---

## Summary Checklist

| # | Test | Pass condition |
|---|---|---|
| 1 | API root | Lists all 5 resource URLs |
| 2 | Surgeon CRUD | Create 201, list paginated, retrieve with `full_name`, patch 200 |
| 3 | OperationType & Step | Create 201 for each |
| 4 | OperationInstance list | No `steps` key in list results |
| 5 | OperationInstance retrieve | `steps` array present with `dist_from_average` |
| 6 | suggested-steps | `[]` with no history; ordered steps with history |
| 7 | complete — success | `complete: true`, `elapsed_time` set, `start_time` chain correct |
| 8 | complete — validation | 400 for already-complete, missing in_room_time, non-sequential times |
| 9 | export-csv | Correct headers, one row per step, correct filename in Content-Disposition |
| 10 | Request logging | `timer.api` JSON line per request with method/path/status/duration_ms |
| 11 | dist_from_average | Non-null float after surgeon has completed ≥2 identical operations |
| 12 | Automated tests | All 51 pass with no unexpected warnings |
