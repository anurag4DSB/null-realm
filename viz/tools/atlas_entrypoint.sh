#!/bin/bash
set -e

echo "=== Embedding Atlas: Exporting data from pgvector ==="
python /app/export_data.py --db-url "$DATABASE_URL" --output-dir /data

echo "=== Embedding Atlas: Generating standalone app ==="
mkdir -p /app/atlas-app

# Use the embedding-atlas CLI to export a standalone application
# --export-application generates a folder with index.html + assets
embedding-atlas /data/embeddings.parquet \
    --text text \
    --x x \
    --y y \
    --export-application /app/atlas-export.zip

# Unzip the standalone app
cd /app/atlas-app
python3 -c "
import zipfile, os
with zipfile.ZipFile('/app/atlas-export.zip', 'r') as z:
    z.extractall('/app/atlas-app')
# If files are in a subdirectory, move them up
entries = os.listdir('/app/atlas-app')
if len(entries) == 1 and os.path.isdir(f'/app/atlas-app/{entries[0]}'):
    subdir = f'/app/atlas-app/{entries[0]}'
    for f in os.listdir(subdir):
        os.rename(f'{subdir}/{f}', f'/app/atlas-app/{f}')
    os.rmdir(subdir)
"

echo "=== Embedding Atlas: Starting nginx ==="
echo "Files in /app/atlas-app:"
ls -la /app/atlas-app/

# Run nginx in foreground
nginx -g 'daemon off;'
