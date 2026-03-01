#!/usr/bin/env bash
set -euo pipefail

EXPECTED_TEAM_ID_DEFAULT="cmlj2267a00ie5q1j6claku9l"
EXPECTED_TEAM_SLUG_DEFAULT="local0ptimist"
EXPECTED_ENV_SLUG_DEFAULT="local0ptimist/helm-orchestration-policy"

expected_team_id="${EXPECTED_TEAM_ID:-$EXPECTED_TEAM_ID_DEFAULT}"
expected_team_slug="${EXPECTED_TEAM_SLUG:-$EXPECTED_TEAM_SLUG_DEFAULT}"
expected_env_slug="${EXPECTED_ENV_SLUG:-$EXPECTED_ENV_SLUG_DEFAULT}"

fail_count=0

pass() {
  printf '[PASS] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1"
  fail_count=$((fail_count + 1))
}

contains() {
  local haystack="$1"
  local needle="$2"
  if command -v rg >/dev/null 2>&1; then
    printf '%s\n' "$haystack" | rg -q "$needle"
  else
    printf '%s\n' "$haystack" | grep -q "$needle"
  fi
}

if command -v prime >/dev/null 2>&1; then
  pass "prime CLI is installed"
else
  fail "prime CLI not found in PATH"
fi

if command -v uv >/dev/null 2>&1; then
  pass "uv is installed"
else
  warn "uv is not installed (needed for Helm commands, not for auth checks)"
fi

if [ "$fail_count" -gt 0 ]; then
  printf '\nPreflight aborted because required CLIs are missing.\n'
  exit 1
fi

config_file="$HOME/.prime/config.json"

if [ -f "$config_file" ]; then
  pass "Prime config exists at $config_file"
else
  fail "Prime config missing at $config_file"
fi

if command -v jq >/dev/null 2>&1 && [ -f "$config_file" ]; then
  api_key_present="$(jq -r '(.api_key // "") != ""' "$config_file")"
  team_id="$(jq -r '.team_id // ""' "$config_file")"
  user_id="$(jq -r '.user_id // ""' "$config_file")"

  if [ "$api_key_present" = "true" ]; then
    pass "API key is configured"
  else
    fail "API key missing in Prime config"
  fi

  if [ -n "$user_id" ]; then
    pass "User ID is configured ($user_id)"
  else
    fail "User ID missing in Prime config"
  fi

  if [ "$team_id" = "$expected_team_id" ]; then
    pass "Team ID matches expected value ($expected_team_id)"
  elif [ -z "$team_id" ]; then
    fail "No Team ID configured; expected $expected_team_id"
  else
    fail "Configured Team ID ($team_id) does not match expected ($expected_team_id)"
  fi
else
  warn "jq not available; skipping direct config JSON checks"
fi

if whoami_out="$(prime whoami 2>&1)"; then
  pass "prime whoami succeeded"
else
  fail "prime whoami failed"
  whoami_out=""
fi

if [ -n "$whoami_out" ]; then
  if contains "$whoami_out" "$expected_team_id"; then
    pass "Authenticated session is tied to expected team ID"
  else
    fail "prime whoami output did not contain expected team ID ($expected_team_id)"
  fi
fi

if teams_out="$(COLUMNS=200 prime teams list 2>&1)"; then
  pass "prime teams list succeeded"
else
  fail "prime teams list failed"
  teams_out=""
fi

if [ -n "$teams_out" ]; then
  if contains "$teams_out" "$expected_team_id"; then
    pass "Expected team ID appears in teams list"
  else
    fail "Expected team ID ($expected_team_id) not found in teams list"
  fi

  if contains "$teams_out" "$expected_team_slug"; then
    pass "Expected team slug appears in teams list"
  else
    fail "Expected team slug ($expected_team_slug) not found in teams list"
  fi
fi

env_ref="${expected_env_slug}@latest"
if env_out="$(prime env info "$env_ref" 2>&1)"; then
  pass "Hub environment is accessible: $env_ref"
else
  fail "Could not access Hub environment: $env_ref"
  env_out=""
fi

if [ -n "$env_out" ] && ! contains "$env_out" "$expected_env_slug"; then
  fail "prime env info output did not include expected env slug ($expected_env_slug)"
fi

printf '\n'
if [ "$fail_count" -eq 0 ]; then
  printf 'Prime terminal preflight passed.\n'
  exit 0
fi

printf 'Prime terminal preflight failed with %s issue(s).\n' "$fail_count"
printf '\nNo-browser recovery checklist:\n'
printf '1) prime config set-api-key <YOUR_PRIME_API_KEY>\n'
printf '2) prime config set-team-id %s\n' "$expected_team_id"
printf '3) prime whoami\n'
printf '4) COLUMNS=200 prime teams list\n'
printf '5) prime env info %s\n' "$env_ref"

exit 1
