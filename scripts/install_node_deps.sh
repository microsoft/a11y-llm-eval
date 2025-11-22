#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../node_runner"
if [ ! -f package.json ]; then
  echo "package.json missing" >&2
  exit 1
fi
npm install
npx playwright install chromium
echo "Node dependencies installed." 
