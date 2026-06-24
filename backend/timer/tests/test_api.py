"""
Integration tests for the timer REST API.

Covers:
- CRUD happy paths: Surgeon, OperationType, Step
- OperationInstance list (flat), create, retrieve (nested)
- suggested-steps: empty with no history, correct steps with history
- complete action: success, rejects already-complete, missing in_room_time,
  missing end_time, non-sequential end_times
- export-csv: correct content-type, headers, row count
"""

import csv
import datetime
import io

import pytest

from timer.models import OperationInstance, OperationType, Step, StepInstance, Surgeon

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def surgeon():
    return Surgeon.objects.create(first_name="Jane", last_name="Smith", email="jane@example.com")


@pytest.fixture
def op_type():
    return OperationType.objects.create(operation_type="Knee Replacement")


@pytest.fixture
def step_incision():
    return Step.objects.create(title="Incision")


@pytest.fixture
def step_closure():
    return Step.objects.create(title="Closure")


@pytest.fixture
def op(surgeon, op_type):
    return OperationInstance.objects.create(
        surgeon=surgeon,
        operation_type=op_type,
        date=datetime.date(2024, 1, 1),
        in_room_time=datetime.time(8, 0),
    )


# ---------------------------------------------------------------------------
# Surgeon CRUD
# ---------------------------------------------------------------------------

class TestSurgeonEndpoints:
    def test_list(self, admin_client, surgeon):
        r = admin_client.get('/api/v1/surgeons/')
        assert r.status_code == 200
        assert r.data['count'] == 1

    def test_create(self, admin_client):
        r = admin_client.post(
            '/api/v1/surgeons/',
            {'first_name': 'Alice', 'last_name': 'Lee', 'email': 'alice@example.com'},
            format='json',
        )
        assert r.status_code == 201
        assert r.data['full_name'] == 'Alice Lee'

    def test_retrieve(self, admin_client, surgeon):
        r = admin_client.get(f'/api/v1/surgeons/{surgeon.pk}/')
        assert r.status_code == 200
        assert r.data['email'] == 'jane@example.com'

    def test_partial_update(self, admin_client, surgeon):
        r = admin_client.patch(f'/api/v1/surgeons/{surgeon.pk}/', {'first_name': 'Janet'}, format='json')
        assert r.status_code == 200
        assert r.data['first_name'] == 'Janet'

    def test_delete(self, admin_client, surgeon):
        r = admin_client.delete(f'/api/v1/surgeons/{surgeon.pk}/')
        assert r.status_code == 204
        assert not Surgeon.objects.filter(pk=surgeon.pk).exists()


# ---------------------------------------------------------------------------
# OperationType
# ---------------------------------------------------------------------------

class TestOperationTypeEndpoints:
    def test_list(self, admin_client, op_type):
        r = admin_client.get('/api/v1/operation-types/')
        assert r.status_code == 200
        assert r.data['count'] == 1

    def test_create(self, admin_client):
        r = admin_client.post('/api/v1/operation-types/', {'operation_type': 'Hip Replacement'}, format='json')
        assert r.status_code == 201
        assert r.data['operation_type'] == 'Hip Replacement'


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------

class TestStepEndpoints:
    def test_list(self, admin_client, step_incision):
        r = admin_client.get('/api/v1/steps/')
        assert r.status_code == 200
        assert r.data['count'] == 1

    def test_create(self, admin_client):
        r = admin_client.post('/api/v1/steps/', {'title': 'Prep'}, format='json')
        assert r.status_code == 201
        assert r.data['title'] == 'Prep'


# ---------------------------------------------------------------------------
# OperationInstance
# ---------------------------------------------------------------------------

class TestOperationInstanceEndpoints:
    def test_list_returns_flat_serializer(self, admin_client, op):
        r = admin_client.get('/api/v1/operation-instances/')
        assert r.status_code == 200
        assert r.data['count'] == 1
        assert 'steps' not in r.data['results'][0]

    def test_create(self, admin_client, surgeon, op_type):
        payload = {
            'surgeon': surgeon.pk,
            'operation_type': op_type.pk,
            'date': '2024-06-01',
        }
        r = admin_client.post('/api/v1/operation-instances/', payload, format='json')
        assert r.status_code == 201
        assert r.data['complete'] is False

    def test_retrieve_includes_nested_steps(self, admin_client, op, step_incision):
        StepInstance.objects.create(step=step_incision, operation_instance=op, order=0)
        r = admin_client.get(f'/api/v1/operation-instances/{op.pk}/')
        assert r.status_code == 200
        assert 'steps' in r.data
        assert len(r.data['steps']) == 1
        assert r.data['steps'][0]['step_title'] == 'Incision'


# ---------------------------------------------------------------------------
# suggested-steps action
# ---------------------------------------------------------------------------

class TestSuggestedSteps:
    def test_empty_with_no_history(self, admin_client, op):
        r = admin_client.get(f'/api/v1/operation-instances/{op.pk}/suggested-steps/')
        assert r.status_code == 200
        assert r.data == []

    def test_returns_steps_from_surgeon_history(
        self, admin_client, surgeon, op_type, step_incision, step_closure
    ):
        ref_op = OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type,
            date=datetime.date(2024, 1, 1), complete=True,
        )
        StepInstance.objects.create(step=step_incision, operation_instance=ref_op, order=0)
        StepInstance.objects.create(step=step_closure, operation_instance=ref_op, order=1)

        new_op = OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type, date=datetime.date(2024, 6, 1),
        )
        r = admin_client.get(f'/api/v1/operation-instances/{new_op.pk}/suggested-steps/')
        assert r.status_code == 200
        assert [s['title'] for s in r.data] == ['Incision', 'Closure']


# ---------------------------------------------------------------------------
# complete action
# ---------------------------------------------------------------------------

class TestCompleteAction:
    def _make_ready_op(self, surgeon, op_type, step_incision, step_closure):
        op = OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type,
            date=datetime.date(2024, 1, 1), in_room_time=datetime.time(8, 0),
        )
        StepInstance.objects.create(
            step=step_incision, operation_instance=op, order=0, end_time=datetime.time(8, 30),
        )
        StepInstance.objects.create(
            step=step_closure, operation_instance=op, order=1, end_time=datetime.time(9, 0),
        )
        return op

    def test_success(self, admin_client, surgeon, op_type, step_incision, step_closure):
        op = self._make_ready_op(surgeon, op_type, step_incision, step_closure)
        r = admin_client.post(f'/api/v1/operation-instances/{op.pk}/complete/')
        assert r.status_code == 200
        assert r.data['complete'] is True
        assert r.data['elapsed_time'] == 3600
        assert len(r.data['steps']) == 2

    def test_already_complete_returns_400(self, admin_client, surgeon, op_type, step_incision, step_closure):
        op = self._make_ready_op(surgeon, op_type, step_incision, step_closure)
        admin_client.post(f'/api/v1/operation-instances/{op.pk}/complete/')
        r = admin_client.post(f'/api/v1/operation-instances/{op.pk}/complete/')
        assert r.status_code == 400
        assert 'already complete' in r.data['detail']

    def test_missing_in_room_time_returns_400(self, admin_client, surgeon, op_type, step_incision):
        op = OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type, date=datetime.date(2024, 1, 1),
        )
        StepInstance.objects.create(
            step=step_incision, operation_instance=op, order=0, end_time=datetime.time(8, 30),
        )
        r = admin_client.post(f'/api/v1/operation-instances/{op.pk}/complete/')
        assert r.status_code == 400

    def test_missing_end_time_returns_400(self, admin_client, surgeon, op_type, step_incision):
        op = OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type,
            date=datetime.date(2024, 1, 1), in_room_time=datetime.time(8, 0),
        )
        StepInstance.objects.create(step=step_incision, operation_instance=op, order=0)
        r = admin_client.post(f'/api/v1/operation-instances/{op.pk}/complete/')
        assert r.status_code == 400
        assert 'Missing end time' in r.data['detail']

    def test_non_sequential_times_returns_400(self, admin_client, surgeon, op_type, step_incision, step_closure):
        op = OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type,
            date=datetime.date(2024, 1, 1), in_room_time=datetime.time(8, 0),
        )
        StepInstance.objects.create(
            step=step_incision, operation_instance=op, order=0, end_time=datetime.time(8, 30),
        )
        StepInstance.objects.create(
            step=step_closure, operation_instance=op, order=1, end_time=datetime.time(8, 15),
        )
        r = admin_client.post(f'/api/v1/operation-instances/{op.pk}/complete/')
        assert r.status_code == 400
        assert 'end time must be after' in r.data['detail']


# ---------------------------------------------------------------------------
# export-csv action
# ---------------------------------------------------------------------------

class TestExportCsv:
    def test_returns_csv_content_type(self, admin_client, op):
        r = admin_client.get(f'/api/v1/operation-instances/{op.pk}/export-csv/')
        assert r.status_code == 200
        assert 'text/csv' in r['Content-Type']

    def test_csv_headers(self, admin_client, op):
        r = admin_client.get(f'/api/v1/operation-instances/{op.pk}/export-csv/')
        reader = csv.reader(io.StringIO(r.content.decode()))
        headers = next(reader)
        assert headers == ['Step', 'Start Time', 'End Time', 'Elapsed Time (s)', 'Dist from Average (%)']

    def test_csv_row_count(self, admin_client, op, step_incision, step_closure):
        StepInstance.objects.create(step=step_incision, operation_instance=op, order=0)
        StepInstance.objects.create(step=step_closure, operation_instance=op, order=1)
        r = admin_client.get(f'/api/v1/operation-instances/{op.pk}/export-csv/')
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        assert len(rows) == 3  # header + 2 step rows
