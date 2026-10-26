#!/bin/bash
# Single entrypoint for local (bare-metal) runs and the Docker image.
set -e
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Starting Sunlease Depot Management"

if [ -n "$DEPOT_RUNNING_IN_DOCKER" ]; then
    cd /app
    python -m app.seed --users      # creates default logins on first start only
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi

cd "$ROOT_DIR/backend"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt

cd "$ROOT_DIR/frontend"
[ -d node_modules ] || npm install
npm run build
rm -rf "$ROOT_DIR/backend/frontend_dist"   # drop bundles from earlier builds
mkdir -p "$ROOT_DIR/backend/frontend_dist"
cp -R dist/. "$ROOT_DIR/backend/frontend_dist/"

cd "$ROOT_DIR/backend"
mkdir -p "$ROOT_DIR/data"
python -m app.seed --users
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8030}"
