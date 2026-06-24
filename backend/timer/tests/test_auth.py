"""
Tests for authentication, authorization, data isolation, and audit logging.

Covers:
- Unauthenticated requests are rejected (401) on protected endpoints
- GET /health/ remains open to unauthenticated requests
- Login success and failure (with audit logging)
- Token refresh
- Logout and token blacklisting
- Per-surgeon data isolation (standard users see only their own records)
- Admin override (is_staff sees all records)
- Write access to reference-data endpoints restricted to admin
- Audit log events for OperationInstance create/update/delete/complete
"""

import datetime
import logging

import pytest
from django.contrib.auth import get_user_model

from timer.models import OperationInstance, OperationType, Step, StepInstance, Surgeon

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_type():
    return OperationType.objects.create(operation_type='Knee Replacement')


@pytest.fixture
def surgeon_a(user):
    """Surgeon linked to the standard test user (auth_client authenticates as this user)."""
    return Surgeon.objects.create(
        user=user, first_name='Alice', last_name='Alpha', email='alice@example.com'
    )


@pytest.fixture
def user_b(db):
    return get_user_model().objects.create_user(username='userb', password='testpass123')


@pytest.fixture
def surgeon_b(user_b):
    return Surgeon.objects.create(
        user=user_b, first_name='Bob', last_name='Beta', email='bob@example.com'
    )


@pytest.fixture
def op_b(surgeon_b, op_type):
    """An operation belonging to surgeon B — invisible to surgeon A."""
    return OperationInstance.objects.create(
        surgeon=surgeon_b, operation_type=op_type, date=datetime.date(2024, 1, 1)
    )


@pytest.fixture
def audit_caplog(caplog):
    """
    Capture timer.audit log records for assertion in tests.

    timer.audit has propagate=False in settings (so audit events don't bleed
    into other loggers), which also prevents caplog from seeing them by default.
    This fixture temporarily enables propagation so caplog can intercept the
    records, then restores the original setting after the test.
    """
    audit_logger = logging.getLogger('timer.audit')
    audit_logger.propagate = True
    with caplog.at_level(logging.INFO, logger='timer.audit'):
        yield caplog
    audit_logger.propagate = False


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

class TestUnauthenticated:
    def test_protected_endpoint_returns_401(self, api_client):
        r = api_client.get('/api/v1/surgeons/')
        assert r.status_code == 401

    def test_health_remains_open(self, api_client):
        r = api_client.get('/health/')
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_success_returns_tokens(self, api_client, user):
        r = api_client.post(
            '/api/v1/auth/login/',
            {'username': 'testuser', 'password': 'testpass123'},
            format='json',
        )
        assert r.status_code == 200
        assert 'access' in r.data
        assert 'refresh' in r.data

    def test_wrong_password_returns_401(self, api_client, user):
        r = api_client.post(
            '/api/v1/auth/login/',
            {'username': 'testuser', 'password': 'wrongpassword'},
            format='json',
        )
        assert r.status_code == 401

    def test_success_emits_audit_log(self, api_client, user, audit_caplog):
        api_client.post(
            '/api/v1/auth/login/',
            {'username': 'testuser', 'password': 'testpass123'},
            format='json',
        )
        assert any(r.msg == 'login_success' for r in audit_caplog.records)

    def test_wrong_password_emits_audit_log(self, api_client, user, audit_caplog):
        api_client.post(
            '/api/v1/auth/login/',
            {'username': 'testuser', 'password': 'wrongpassword'},
            format='json',
        )
        assert any(r.msg == 'login_failure' for r in audit_caplog.records)


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    def test_valid_refresh_returns_new_access(self, api_client, user):
        login = api_client.post(
            '/api/v1/auth/login/',
            {'username': 'testuser', 'password': 'testpass123'},
            format='json',
        )
        r = api_client.post(
            '/api/v1/auth/refresh/',
            {'refresh': login.data['refresh']},
            format='json',
        )
        assert r.status_code == 200
        assert 'access' in r.data


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def _login(self, client):
        return client.post(
            '/api/v1/auth/login/',
            {'username': 'testuser', 'password': 'testpass123'},
            format='json',
        ).data

    def test_logout_returns_204(self, api_client, auth_client, user):
        tokens = self._login(api_client)
        r = auth_client.post(
            '/api/v1/auth/logout/', {'refresh': tokens['refresh']}, format='json'
        )
        assert r.status_code == 204

    def test_logout_emits_audit_log(self, api_client, auth_client, user, audit_caplog):
        tokens = self._login(api_client)
        auth_client.post(
            '/api/v1/auth/logout/', {'refresh': tokens['refresh']}, format='json'
        )
        assert any(r.msg == 'logout' for r in audit_caplog.records)

    def test_blacklisted_token_cannot_be_refreshed(self, api_client, auth_client, user):
        tokens = self._login(api_client)
        auth_client.post(
            '/api/v1/auth/logout/', {'refresh': tokens['refresh']}, format='json'
        )
        r = api_client.post(
            '/api/v1/auth/refresh/', {'refresh': tokens['refresh']}, format='json'
        )
        assert r.status_code == 401

    def test_missing_refresh_token_returns_400(self, auth_client, user):
        r = auth_client.post('/api/v1/auth/logout/', {}, format='json')
        assert r.status_code == 400

    def test_unauthenticated_logout_returns_401(self, api_client, user):
        tokens = self._login(api_client)
        r = api_client.post(
            '/api/v1/auth/logout/', {'refresh': tokens['refresh']}, format='json'
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestDataIsolation:
    def test_surgeon_cannot_list_other_surgeon_operations(
        self, auth_client, surgeon_a, op_b
    ):
        r = auth_client.get('/api/v1/operation-instances/')
        assert r.status_code == 200
        assert r.data['count'] == 0

    def test_surgeon_cannot_retrieve_other_surgeon_operation(
        self, auth_client, surgeon_a, op_b
    ):
        r = auth_client.get(f'/api/v1/operation-instances/{op_b.pk}/')
        assert r.status_code == 404

    def test_admin_sees_all_operations(self, admin_client, surgeon_a, op_b):
        r = admin_client.get('/api/v1/operation-instances/')
        assert r.status_code == 200
        assert r.data['count'] == 1

    def test_standard_user_cannot_write_reference_data(self, auth_client):
        r = auth_client.post(
            '/api/v1/surgeons/',
            {'first_name': 'Eve', 'last_name': 'Evil', 'email': 'eve@example.com'},
            format='json',
        )
        assert r.status_code == 403

    def test_admin_can_write_reference_data(self, admin_client):
        r = admin_client.post(
            '/api/v1/surgeons/',
            {'first_name': 'Carol', 'last_name': 'Correct', 'email': 'carol@example.com'},
            format='json',
        )
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Audit logging — OperationInstance mutations
# ---------------------------------------------------------------------------

class TestAuditLogging:
    @pytest.fixture
    def surgeon(self):
        return Surgeon.objects.create(
            first_name='Test', last_name='Surgeon', email='test@example.com'
        )

    @pytest.fixture
    def op(self, surgeon, op_type):
        return OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type, date=datetime.date(2024, 1, 1)
        )

    def test_create_emits_audit_event(self, admin_client, surgeon, op_type, audit_caplog):
        admin_client.post(
            '/api/v1/operation-instances/',
            {'surgeon': surgeon.pk, 'operation_type': op_type.pk, 'date': '2024-06-01'},
            format='json',
        )
        assert any(r.msg == 'operation_create' for r in audit_caplog.records)

    def test_update_emits_audit_event(self, admin_client, op, audit_caplog):
        admin_client.patch(
            f'/api/v1/operation-instances/{op.pk}/',
            {'detail': 'updated note'},
            format='json',
        )
        assert any(r.msg == 'operation_update' for r in audit_caplog.records)

    def test_destroy_emits_audit_event(self, admin_client, op, audit_caplog):
        admin_client.delete(f'/api/v1/operation-instances/{op.pk}/')
        assert any(r.msg == 'operation_delete' for r in audit_caplog.records)

    def test_complete_emits_audit_event_with_user_id(
        self, admin_client, admin_user, surgeon, op_type, audit_caplog
    ):
        step = Step.objects.create(title='Incision')
        op = OperationInstance.objects.create(
            surgeon=surgeon, operation_type=op_type,
            date=datetime.date(2024, 1, 1), in_room_time=datetime.time(8, 0),
        )
        StepInstance.objects.create(
            step=step, operation_instance=op, order=0, end_time=datetime.time(8, 30),
        )
        admin_client.post(f'/api/v1/operation-instances/{op.pk}/complete/')
        records = [r for r in audit_caplog.records if r.msg == 'operation_complete']
        assert records
        assert records[0].user_id == admin_user.id
