#!/usr/bin/env bash
# Prepare a development checkout; no production credentials or services are used.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${CODEX_PYTHON:-python3.11}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  printf '%s\n' 'Select CPython 3.11 in the environment, or set CODEX_PYTHON to it.' >&2
  exit 1
fi
"$python_bin" -c 'import sys; assert sys.version_info[:2] == (3, 11), "CPython 3.11 is required"'
node -e 'const [major, minor, patch] = process.versions.node.split(".").map(Number); if (major !== 24 || minor !== 21 || patch !== 0) { throw new Error("Select Node.js 24.21.0 from tooling/toolchain.json"); }'
test "$(npm --version)" = '11.20.0'

if [[ ! -x backend/.venv/bin/python ]]; then
  "$python_bin" scripts/bootstrap_backend.py
fi
backend/.venv/bin/python scripts/bootstrap_backend.py --check
backend/.venv/bin/python -m pip install --require-hashes -r mcp-connector/requirements.lock

npm ci --prefix frontend --no-audit --no-fund
npm ci --prefix mobile --no-audit --no-fund

printf '%s\n' \
  'Development dependencies are ready.' \
  'Activate backend/.venv/bin/activate for Python commands.' \
  'Use the verification commands in AGENTS.md and synthetic test fixtures.' \
  'PostgreSQL, Redis, private object storage and browser binaries are separate test services.'
