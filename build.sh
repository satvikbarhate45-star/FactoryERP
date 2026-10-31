#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

# Install production dependencies
pip install -r requirements.txt

# Collect static files into STATIC_ROOT using WhiteNoise
python manage.py collectstatic --noinput

# Apply database schema migrations
python manage.py migrate

# External REST/IoT API historical ingestion (Strictly-once from company startup to yesterday)
python manage.py ingest_historical_api --start-date 2026-08-25

# Execute local ML forecasting pipeline for today & upcoming operational days (Zero external API calls)
python manage.py run_local_ml_pipeline --date today --days-ahead 3

# Execute autonomous ML gap detection and backfill missing operational days (Monday, Tuesday, etc.)
python manage.py daily_imputation --days 14

# Enforce monthly employee payroll distribution and purge legacy daily wages
python manage.py sync_monthly_payroll --start-date 2026-08-25

