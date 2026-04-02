#!/bin/bash
set -e

echo "=== TensorBoard Projector: Exporting data from pgvector ==="
python /app/export_data.py --db-url "$DATABASE_URL" --output-dir /data

echo "=== TensorBoard Projector: Copying TSV files ==="
cp /data/vectors.tsv /app/projector/data/vectors.tsv
cp /data/metadata.tsv /app/projector/data/metadata.tsv

# Also copy to oss_data for the default projector config
cp /data/vectors.tsv /app/projector/oss_data/vectors.tsv
cp /data/metadata.tsv /app/projector/oss_data/metadata.tsv

echo "=== TensorBoard Projector: Writing projector config ==="
# The standalone projector reads oss_demo_config.json for its default dataset
cat > /app/projector/oss_demo_config.json <<'EOF'
{
  "embeddings": [
    {
      "tensorName": "Null Realm Code Embeddings (768-dim)",
      "tensorShape": [48, 768],
      "tensorPath": "data/vectors.tsv",
      "metadataPath": "data/metadata.tsv"
    }
  ]
}
EOF

echo "=== TensorBoard Projector: Starting nginx ==="
echo "Files in /app/projector/data/:"
ls -la /app/projector/data/
wc -l /app/projector/data/vectors.tsv /app/projector/data/metadata.tsv

# Run nginx in foreground
nginx -g 'daemon off;'
