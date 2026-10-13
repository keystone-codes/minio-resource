#!/usr/bin/env bats

bats_require_minimum_version 1.5.0

setup() {
  ln -s "$BATS_TEST_DIRNAME/fake-mc" "$BATS_TEST_TMPDIR/mc"
  export PATH="$BATS_TEST_TMPDIR:$PATH"
  export FAKE_MC_LOG="$BATS_TEST_TMPDIR/mc.log"
  export FAKE_MC_STDIN="$BATS_TEST_TMPDIR/mc.stdin"
  : >"$FAKE_MC_LOG"
  : >"$FAKE_MC_STDIN"
  unset FAKE_MC_SCENARIO
  export MINIO_ROOT_USER="rootuser"
  export MINIO_ROOT_PASSWORD="root-password-not-for-argv"
  SCRIPT="$BATS_TEST_DIRNAME/../provision.sh"
  SECRET="$BATS_TEST_TMPDIR/file-mcp.secret"
}

assert_secret_absent() {
  haystack=$1
  needle=$2
  if printf '%s' "$haystack" | grep -F -q -- "$needle"; then
    echo "a secret appeared in command output" >&2
    return 1
  fi
}

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%OLp' "$1"
}

@test "creates bucket, user, policy and prints json" {
  run --separate-stderr "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET"
  [ "$status" -eq 0 ]
  [ "$(printf '%s\n' "$output" | wc -l | tr -d '[:space:]')" -eq 1 ]
  printf '%s\n' "$output" >"$BATS_TEST_TMPDIR/out.json"
  python3 - "$BATS_TEST_TMPDIR/out.json" "$SECRET" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
secret_file = sys.argv[2]
assert payload == {
    "interface": "s3/v1",
    "endpoint": "http://minio-server:9000",
    "region": "us-east-1",
    "bucket": "file-mcp",
    "access_key": "file-mcp",
    "path_style": True,
    "secret_key_file": secret_file,
}, payload
assert "secret_key" not in payload
PY
  log=$(cat "$FAKE_MC_LOG")
  python3 - "$FAKE_MC_LOG" <<'PY'
import sys

lines = [line for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
needles = [
    "alias import",
    "ready",
    "admin info",
    "mb --ignore-existing",
    "admin user add",
    "admin policy create",
    "admin user info",
    "admin policy attach",
    "alias import",
    "ls",
]
start = 0
for needle in needles:
    found = None
    for index, line in enumerate(lines):
        if index < start:
            continue
        if needle in line:
            found = index
            break
    if found is None:
        raise SystemExit(f"missing {needle} after position {start}: {lines}")
    start = found + 1
PY
}

@test "secrets never appear in argv or output" {
  consumer_secret="consumer-secret-not-for-argv"
  printf '%s\n' "$consumer_secret" >"$SECRET"
  chmod 600 "$SECRET"
  run --separate-stderr "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET"
  [ "$status" -eq 0 ]
  combined="$output$stderr$(cat "$FAKE_MC_LOG")"
  assert_secret_absent "$combined" "$MINIO_ROOT_PASSWORD"
  assert_secret_absent "$combined" "$consumer_secret"
  stdin=$(cat "$FAKE_MC_STDIN")
  printf '%s' "$stdin" | grep -F -q -- "$MINIO_ROOT_PASSWORD"
  printf '%s' "$stdin" | grep -F -q -- "$consumer_secret"
}

@test "generates secret file with mode 600" {
  [ ! -e "$SECRET" ]
  run --separate-stderr "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET"
  [ "$status" -eq 0 ]
  [ -f "$SECRET" ]
  [ "$(file_mode "$SECRET")" = "600" ]
  python3 - "$SECRET" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read().splitlines()
assert len(text) >= 1
assert re.fullmatch(r"[0-9a-f]{64}", text[0]), "secret is not 64 hex characters"
PY
}

@test "reuses existing secret file" {
  existing="abc123existingsecretvalue"
  printf '%s\n' "$existing" >"$SECRET"
  chmod 600 "$SECRET"
  before=$(cat "$SECRET")
  run --separate-stderr "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET"
  [ "$status" -eq 0 ]
  [ "$(cat "$SECRET")" = "$before" ]
  stdin=$(cat "$FAKE_MC_STDIN")
  printf '%s' "$stdin" | grep -F -q -- "$existing"
}

@test "second run skips attach when policy is attached" {
  export FAKE_MC_SCENARIO=policy-attached
  run --separate-stderr "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET" \
    --region us-east-1
  [ "$status" -eq 0 ]
  printf '%s\n' "$output" >"$BATS_TEST_TMPDIR/out.json"
  python3 - "$BATS_TEST_TMPDIR/out.json" "$SECRET" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
assert payload["interface"] == "s3/v1"
assert payload["bucket"] == "file-mcp"
assert payload["access_key"] == "file-mcp"
assert payload["path_style"] is True
assert payload["secret_key_file"] == sys.argv[2]
assert payload["region"] == "us-east-1"
assert payload["endpoint"] == "http://minio-server:9000"
PY
  if grep -F -q "admin policy attach" "$FAKE_MC_LOG"; then
    echo "policy attach was called" >&2
    return 1
  fi
}

@test "rejects bad consumer names" {
  long=$(python3 -c 'print("a" * 64)')
  for name in File_MCP a x..y "$long"; do
    run --separate-stderr "$SCRIPT" \
      --consumer "$name" \
      --endpoint http://minio-server:9000 \
      --secret-file "$SECRET"
    [ "$status" -eq 2 ]
  done
}

@test "requires root credentials in environment" {
  run --separate-stderr env -u MINIO_ROOT_PASSWORD "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET"
  [ "$status" -eq 2 ]
}

@test "fails with 3 when provider is not ready" {
  export FAKE_MC_SCENARIO=not-ready
  run --separate-stderr "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET" \
    --ready-timeout 2
  [ "$status" -eq 3 ]
  printf '%s' "$stderr" | grep -F -q "not ready"
  printf '%s' "$stderr" | grep -F -q "http://minio-server:9000"
  printf '%s' "$stderr" | grep -F -q "2s"
}

@test "policy grants only the consumer bucket" {
  run --separate-stderr "$SCRIPT" \
    --consumer file-mcp \
    --endpoint http://minio-server:9000 \
    --secret-file "$SECRET"
  [ "$status" -eq 0 ]
  policy=/tmp/policy.json
  [ -f "$policy" ]
  python3 - "$policy" <<'PY'
import json
import sys

document = json.loads(open(sys.argv[1], encoding="utf-8").read())
allowed = {
    "s3:ListBucket",
    "s3:GetBucketLocation",
    "s3:GetLifecycleConfiguration",
    "s3:PutLifecycleConfiguration",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
}
seen = set()
for statement in document["Statement"]:
    assert statement["Effect"] == "Allow"
    resources = statement["Resource"]
    if isinstance(resources, str):
        resources = [resources]
    for resource in resources:
        assert resource in {"arn:aws:s3:::file-mcp", "arn:aws:s3:::file-mcp/*"}, resource
    actions = statement["Action"]
    if isinstance(actions, str):
        actions = [actions]
    for action in actions:
        assert action not in {"s3:*", "admin:*", "s3:CreateBucket", "s3:ListAllMyBuckets"}
        assert not action.startswith("admin:")
        seen.add(action)
assert seen == allowed
PY
}
