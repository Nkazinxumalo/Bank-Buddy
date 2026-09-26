#!/bin/bash
cd "$(dirname "$0")"
source antenv/bin/activate
exec gunicorn --bind=0.0.0.0:8000 --timeout 600 run:app