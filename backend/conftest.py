import os
from pathlib import Path


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
