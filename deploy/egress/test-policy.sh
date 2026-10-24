#!/usr/bin/env sh
# Starts the egress proxy in the given mode and checks what it lets through. Needs Docker and internet access.
#   docker build -t citesure-egress deploy/egress && deploy/egress/test-policy.sh allowlist|open
set -eu
MODE="${1:-allowlist}"
NAME="citesure-egress-policy-$$"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$NAME" -e EGRESS_MODE="$MODE" "${IMAGE:-citesure-egress}" >/dev/null
sleep 3
IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME")"
fail=0
code() { docker run --rm curlimages/curl:8.10.1 -s -o /dev/null -w '%{http_code}' -m 25 -x "http://$IP:3128" "$1" 2>/dev/null || true; }
expect() { # expect <description> <url> <allowed|denied>
  got="$(code "$2")"
  if { [ "$3" = allowed ] && [ "$got" = 200 ]; } || { [ "$3" = denied ] && [ "$got" != 200 ]; }; then
    echo "PASS  [$MODE] $1 ($got)"
  else
    echo "FAIL  [$MODE] $1: expected $3, got HTTP '$got'"; fail=1
  fi
}
expect "an allow-listed scholarly API"         "https://export.arxiv.org/api/query?search_query=all:attention&max_results=1" allowed
expect "a cloud metadata address"              "https://169.254.169.254/latest/meta-data/" denied
expect "a private network address"             "https://10.0.0.1/" denied
expect "a loopback address"                    "https://127.0.0.1/" denied
if [ "$MODE" = allowlist ]; then
  expect "a host that is not on the allow-list" "https://example.com/" denied
else
  expect "an arbitrary public page"             "https://example.com/" allowed
fi
exit "$fail"
