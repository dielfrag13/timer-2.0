FROM python:3.12-slim

# Install system packages:
#   postgresql-client  — provides pg_isready, used in entrypoint.sh to wait
#                        for Postgres before running migrations
#   curl               — used by the HEALTHCHECK in docker-compose.yml to probe
#                        GET /health/ on each interval
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-client \
       curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first so Docker can cache the pip install layer.
# This layer is only rebuilt when requirements.txt changes, not on every
# code change — which is the most expensive layer to rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source.
COPY . .

# Collect static files at build time so they are baked into the image.
# Django must load settings to run collectstatic, which requires SECRET_KEY
# and DATABASE_URL to be present. The real values are runtime secrets and
# must not be baked into the image, so we pass throwaway values here.
# collectstatic never connects to the database, so the dummy DATABASE_URL
# is never actually used for a connection.
RUN SECRET_KEY=dummy-for-collectstatic \
    DATABASE_URL=postgres://none:none@localhost/none \
    python manage.py collectstatic --noinput

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "timer_server.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
