#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

# Install production dependencies
pip install -r requirements.txt

# Collect static files into STATIC_ROOT using WhiteNoise
python manage.py collectstatic --noinput

# Apply database schema migrations
python manage.py migrate

# Execute autonomous ML gap detection and backfill missing operational days (Monday, Tuesday, etc.)
python manage.py daily_imputation --days 14
