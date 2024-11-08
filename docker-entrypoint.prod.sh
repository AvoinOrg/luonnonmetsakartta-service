#!/bin/bash
source /root/.bashrc >/dev/null 2>&1

poetry install
# ./wait-for-it.sh "${POSTGRES_HOST}":"${POSTGRES_PORT}" --timeout=60 --strict -- echo "PostgreSQL is up"
# ./wait-for-it.sh "${REDIS_HOST}":"${REDIS_PORT}" --timeout=60 --strict -- echo "Redis is up"
poetry run gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:80
# tail -f /dev/null # the actual server is running in vpn-relay