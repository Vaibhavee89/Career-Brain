#!/bin/sh
# Start the API. On hosts without the data mounted (Render), fetch the brain
# repo with a read-only token and serve only its public pages. Without a token,
# serve whatever is mounted at CAREERBRAIN_ROOT (local docker compose).
set -eu

if [ -n "${CAREERBRAIN_DATA_TOKEN:-}" ]; then
  repo="${CAREERBRAIN_DATA_REPO:-Vaibhavee89/careerbrain-data}"
  url="${CAREERBRAIN_DATA_URL:-https://github.com/$repo.git}"
  work="$(mktemp -d)"
  # Pass the token as a header, not in the URL, so it isn't written to .git/config.
  auth="$(printf 'x-access-token:%s' "$CAREERBRAIN_DATA_TOKEN" | base64 | tr -d '\n')"

  if ! git -c "http.extraheader=AUTHORIZATION: basic $auth" \
      clone --depth 1 --quiet "$url" "$work/data"; then
    echo "could not fetch brain data from $url" >&2
    exit 1
  fi

  export CAREERBRAIN_ROOT="$(mktemp -d)"
  python -m careerbrain.sync --src "$work/data" --dst "$CAREERBRAIN_ROOT"
  rm -rf "$work"
fi

exec python -m careerbrain.adapters.http_api --host 0.0.0.0 --port "${PORT:-8000}"
