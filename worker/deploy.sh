#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
DB_NAME="pd-lab-chatbot-db"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

if [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  export CLOUDFLARE_ACCOUNT_ID
fi

if [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
  export CLOUDFLARE_API_TOKEN
fi

cd "$SCRIPT_DIR"

for name in LLM_API_KEY LLM_API_BASE LLM_MODEL DISCORD_WEBHOOK_URL MAX_MESSAGES RATE_LIMIT; do
  value="$(eval "printf '%s' \"\${$name:-}\"")"
  if [ -n "$value" ]; then
    printf '%s' "$value" | npx wrangler secret put "$name"
  fi
done

DB_ID="$(npx wrangler d1 list --json | node -e '
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const databases = JSON.parse(input || "[]");
  const db = databases.find(item => item.name === process.argv[1]);
  process.stdout.write(db ? (db.uuid || db.database_id || db.id || "") : "");
});
' "$DB_NAME")"

if [ -z "$DB_ID" ]; then
  npx wrangler d1 create "$DB_NAME"
  DB_ID="$(npx wrangler d1 list --json | node -e '
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const databases = JSON.parse(input || "[]");
  const db = databases.find(item => item.name === process.argv[1]);
  process.stdout.write(db ? (db.uuid || db.database_id || db.id || "") : "");
});
' "$DB_NAME")"
fi

if [ -z "$DB_ID" ]; then
  echo "Could not determine D1 database id for $DB_NAME" >&2
  exit 1
fi

sed -i.bak "s/database_id = \"REPLACE_WITH_D1_DATABASE_ID\"/database_id = \"$DB_ID\"/" wrangler.toml
rm -f wrangler.toml.bak

npx wrangler d1 execute "$DB_NAME" --file=schema.sql
npx wrangler deploy
