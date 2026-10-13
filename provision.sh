#!/bin/sh
# Give one service its own bucket and user. Secrets stay in the environment,
# on stdin of mc, or in the mode-600 secret file. They are never arguments.
set -eu

die() {
  code=$1
  shift
  printf '%s\n' "$*" >&2
  exit "$code"
}

json_escape() {
  rest=$1
  out=
  while [ -n "$rest" ]; do
    rest_tail=${rest#?}
    ch=${rest%"$rest_tail"}
    case $ch in
      \\) out=${out}\\\\ ;;
      '"') out=${out}\\\" ;;
      *) out=${out}${ch} ;;
    esac
    rest=$rest_tail
  done
  printf '%s' "$out"
}

subst_token() {
  text=$1
  token=$2
  value=$3
  out=
  while :; do
    case $text in
      *"$token"*)
        out=$out${text%%"$token"*}$value
        text=${text#*"$token"}
        ;;
      *)
        printf '%s' "$out$text"
        return
        ;;
    esac
  done
}

need_value() {
  if [ $# -lt 2 ] || [ -z "$2" ]; then
    die 2 "Missing value for $1."
  fi
}

consumer=
endpoint=
secret_file=
region=us-east-1
ready_timeout=60

while [ $# -gt 0 ]; do
  case $1 in
    --consumer)
      need_value "$@"
      consumer=$2
      shift 2
      ;;
    --endpoint)
      need_value "$@"
      endpoint=$2
      shift 2
      ;;
    --secret-file)
      need_value "$@"
      secret_file=$2
      shift 2
      ;;
    --region)
      need_value "$@"
      region=$2
      shift 2
      ;;
    --ready-timeout)
      need_value "$@"
      ready_timeout=$2
      shift 2
      ;;
    *)
      die 2 "Unknown argument: $1"
      ;;
  esac
done

if [ -z "$consumer" ] || [ -z "$endpoint" ] || [ -z "$secret_file" ]; then
  die 2 "Required arguments: --consumer, --endpoint, --secret-file."
fi

case $consumer in
  *[!a-z0-9-]*) die 2 "Consumer name must match a bucket name: lowercase letters, digits, and hyphens." ;;
  [a-z0-9]*[a-z0-9]) ;;
  *) die 2 "Consumer name must match a bucket name: lowercase letters, digits, and hyphens." ;;
esac
consumer_len=$(printf '%s' "$consumer" | wc -c | tr -d '[:space:]')
if [ "$consumer_len" -lt 3 ] || [ "$consumer_len" -gt 63 ]; then
  die 2 "Consumer name must be 3 to 63 characters."
fi

case $region in
  *[!a-z0-9-]*) die 2 "Region must be 1 to 32 characters of lowercase letters, digits, and hyphens." ;;
esac
region_len=$(printf '%s' "$region" | wc -c | tr -d '[:space:]')
if [ "$region_len" -lt 1 ] || [ "$region_len" -gt 32 ]; then
  die 2 "Region must be 1 to 32 characters of lowercase letters, digits, and hyphens."
fi

case $ready_timeout in
  ''|*[!0-9]*) die 2 "--ready-timeout must be a positive number of seconds." ;;
esac
if [ "$ready_timeout" -lt 1 ]; then
  die 2 "--ready-timeout must be a positive number of seconds."
fi

if [ -z "${MINIO_ROOT_USER-}" ] || [ -z "${MINIO_ROOT_PASSWORD-}" ]; then
  die 2 "MINIO_ROOT_USER and MINIO_ROOT_PASSWORD must be set in the environment."
fi

pkg=$(unset CDPATH; cd -- "$(dirname "$0")" && pwd)
template=$pkg/policy/bucket-rw.json.tmpl
if [ ! -f "$template" ]; then
  die 2 "Policy template not found next to provision.sh."
fi

printf '%s\n' "Signing in to MinIO at $endpoint." >&2
alias_json=$(printf '{"url":"%s","accessKey":"%s","secretKey":"%s","api":"s3v4","path":"auto"}' \
  "$(json_escape "$endpoint")" \
  "$(json_escape "$MINIO_ROOT_USER")" \
  "$(json_escape "$MINIO_ROOT_PASSWORD")")
if ! printf '%s\n' "$alias_json" | mc alias import provider >/dev/null 2>&1; then
  die 3 "Could not sign in to MinIO at $endpoint."
fi

printf '%s\n' "Waiting until MinIO is ready (up to ${ready_timeout}s)." >&2
elapsed=0
ready=0
while [ "$elapsed" -lt "$ready_timeout" ]; do
  if mc ready provider >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
  elapsed=$((elapsed + 1))
done
if [ "$ready" -ne 1 ]; then
  die 3 "MinIO at $endpoint is not ready after ${ready_timeout}s."
fi

admin_failed=0
info_err=$(mc admin info provider 2>&1 >/dev/null) || admin_failed=1
if [ "$admin_failed" -ne 0 ]; then
  case "$info_err" in
    *"signature we calculated does not match"* | *"Access Denied"* | *"InvalidAccessKeyId"*)
      die 3 "MinIO root credentials do not match the credentials stored with the data volume. This happens when the root password changed after the volume was created."
      ;;
  esac
  die 3 "MinIO at $endpoint rejected the root credentials."
fi

printf '%s\n' "Creating bucket $consumer." >&2
if ! mc mb --ignore-existing "provider/$consumer" >/dev/null 2>&1; then
  die 3 "Could not create bucket $consumer."
fi

if [ -s "$secret_file" ]; then
  IFS= read -r secret <"$secret_file" || die 2 "Could not read the consumer secret file."
  if [ -z "$secret" ]; then
    die 2 "The consumer secret file is empty."
  fi
else
  if ! command -v od >/dev/null 2>&1 || ! command -v tr >/dev/null 2>&1; then
    die 2 "pass a pre-generated secret file"
  fi
  secret=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n') || die 2 "pass a pre-generated secret file"
  secret_len=$(printf '%s' "$secret" | wc -c | tr -d '[:space:]')
  if [ "$secret_len" -ne 64 ]; then
    die 2 "pass a pre-generated secret file"
  fi
  secret_dir=$(dirname "$secret_file")
  if [ ! -d "$secret_dir" ] || [ ! -w "$secret_dir" ]; then
    die 2 "Cannot create the consumer secret file."
  fi
  umask 077
  if ! printf '%s\n' "$secret" >"$secret_file"; then
    die 2 "Cannot create the consumer secret file."
  fi
  chmod 600 "$secret_file" || die 2 "Cannot create the consumer secret file."
  printf '%s\n' "Wrote a new consumer secret." >&2
fi

printf '%s\n' "Creating user $consumer." >&2
if ! printf '%s\n' "$secret" | mc admin user add provider "$consumer" >/dev/null 2>&1; then
  die 3 "Could not create user $consumer."
fi

policy=$consumer-bucket-rw
policy_body=$(subst_token "$(cat "$template")" "__BUCKET__" "$consumer")
if ! printf '%s\n' "$policy_body" >/tmp/policy.json; then
  die 2 "Could not write the consumer policy."
fi
printf '%s\n' "Creating policy $policy." >&2
if ! mc admin policy create provider "$policy" /tmp/policy.json >/dev/null 2>&1; then
  die 3 "Could not create policy $policy."
fi

user_info=$(mc admin user info provider "$consumer" --json 2>/dev/null) || die 3 "Could not read user $consumer."
case $user_info in
  *"\"$policy\""*)
    printf '%s\n' "Policy $policy is already attached." >&2
    ;;
  *)
    printf '%s\n' "Attaching policy $policy." >&2
    if ! mc admin policy attach provider "$policy" --user "$consumer" >/dev/null 2>&1; then
      die 3 "Could not attach policy $policy."
    fi
    ;;
esac

printf '%s\n' "Checking access to bucket $consumer." >&2
consumer_json=$(printf '{"url":"%s","accessKey":"%s","secretKey":"%s","api":"s3v4","path":"auto"}' \
  "$(json_escape "$endpoint")" \
  "$(json_escape "$consumer")" \
  "$(json_escape "$secret")")
if ! printf '%s\n' "$consumer_json" | mc alias import consumer >/dev/null 2>&1; then
  die 3 "Could not sign in as $consumer."
fi
if ! mc ls "consumer/$consumer" >/dev/null 2>&1; then
  die 3 "User $consumer cannot list bucket $consumer."
fi

printf '{"interface":"s3/v1","endpoint":"%s","region":"%s","bucket":"%s","access_key":"%s","path_style":true,"secret_key_file":"%s"}\n' \
  "$(json_escape "$endpoint")" \
  "$(json_escape "$region")" \
  "$(json_escape "$consumer")" \
  "$(json_escape "$consumer")" \
  "$(json_escape "$secret_file")"
