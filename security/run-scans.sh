#!/usr/bin/env bash
# Deterministic security scans. Raw outputs go to security/scan-results/ (committed as evidence).
# Needs Docker (for gitleaks, Semgrep, Trivy) and uv/npm. Run from the repository root:  bash security/run-scans.sh
set -u
cd "$(dirname "$0")/.."
OUT=security/scan-results
mkdir -p "$OUT"
export MSYS_NO_PATHCONV=1   # keep Git Bash from rewriting container paths on Windows
ROOT="$(pwd -W 2>/dev/null || pwd)"

echo "== gitleaks (secrets in files)"
docker run --rm -v "$ROOT:/repo" ghcr.io/gitleaks/gitleaks:latest dir /repo --config /repo/.gitleaks.toml --redact --no-banner \
  > "$OUT/gitleaks.txt" 2>&1; echo "exit $?" >> "$OUT/gitleaks.txt"

echo "== semgrep (static analysis)"
docker run --rm -v "$ROOT:/src" semgrep/semgrep semgrep scan --config p/python --config p/typescript --config p/react \
  --config p/dockerfile --config p/github-actions --metrics=off --exclude node_modules --exclude .venv --exclude dist --exclude uploads \
  --exclude security /src/backend/app /src/backend/migrations /src/frontend/src /src/mcp-server /src/agent-hooks /src/custom-agent /src/.github /src/backend/Dockerfile /src/frontend/Dockerfile \
  > "$OUT/semgrep.txt" 2>&1; echo "exit $?" >> "$OUT/semgrep.txt"

echo "== trivy fs (dependencies, misconfiguration, secrets)"
docker run --rm -v "$ROOT:/repo" aquasec/trivy:latest fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL \
  --timeout 20m --skip-dirs '**/node_modules,**/.venv,**/dist,**/uploads,**/playwright-report,**/test-results,security/scan-results' /repo \
  > "$OUT/trivy-fs.txt" 2>&1; echo "exit $?" >> "$OUT/trivy-fs.txt"

echo "== pip-audit (Python dependencies)"
( cd backend && uv export --frozen --no-dev --no-hashes -o /tmp/citesure-requirements.txt >/dev/null 2>&1 \
  && uvx pip-audit -r /tmp/citesure-requirements.txt ) > "$OUT/pip-audit.txt" 2>&1; echo "exit $?" >> "$OUT/pip-audit.txt"

echo "== npm audit (JavaScript dependencies)"
( cd frontend && npm audit --omit=dev ) > "$OUT/npm-audit-frontend.txt" 2>&1; echo "exit $?" >> "$OUT/npm-audit-frontend.txt"
( cd e2e && npm audit ) > "$OUT/npm-audit-e2e.txt" 2>&1; echo "exit $?" >> "$OUT/npm-audit-e2e.txt"

echo "Done. See $OUT/"
