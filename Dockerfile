FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

COPY backend/       ./backend/
COPY airflow/       ./airflow/
COPY logging_config.py .
COPY alembic.ini    .
COPY alembic/       ./alembic/
COPY static/        ./static/

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
