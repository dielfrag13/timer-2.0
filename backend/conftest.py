import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


def pytest_configure(config):
    """
    Load .env and set required env var defaults before Django initialises.
    pytest_configure fires before pytest-django sets up Django, so env vars
    set here are visible to settings.py.
    """
    import environ

    env_file = Path(__file__).resolve().parent / '.env'
    if env_file.exists():
        environ.Env.read_env(env_file)

    os.environ.setdefault('SECRET_KEY', 'test-only-secret-key-not-for-production')
    os.environ.setdefault('DATABASE_URL', 'postgres://timer:password@localhost:5432/timer')


@pytest.fixture
def api_client():
    """Unauthenticated client — use for testing 401 responses."""
    return APIClient()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username='testuser', password='testpass123'
    )


@pytest.fixture
def auth_client(user):
    """Authenticated client — force-authenticates as a standard user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def admin_user(db):
    return get_user_model().objects.create_user(
        username='adminuser', password='adminpass123', is_staff=True
    )


@pytest.fixture
def admin_client(admin_user):
    """Authenticated client — force-authenticates as an admin (is_staff) user."""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client
