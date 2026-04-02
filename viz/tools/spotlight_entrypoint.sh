#!/bin/bash
set -e

echo "=== Spotlight: Exporting data from pgvector ==="
python /app/export_data.py --db-url "$DATABASE_URL" --output-dir /data

echo "=== Spotlight: Starting server ==="
python /app/spotlight_server.py
