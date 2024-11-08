#!/bin/bash
source /root/.bashrc >/dev/null 2>&1


poetry install
# reload dir still does not work properly, maybe one day
poetry run uvicorn --host 0.0.0.0 --port 80 --reload --reload-dir "${PWD}/app" app.main:app &
poetry run jupyter notebook --ip='*' --NotebookApp.token="${NOTEBOOK_TOKEN}" --NotebookApp.password='' --allow-root

