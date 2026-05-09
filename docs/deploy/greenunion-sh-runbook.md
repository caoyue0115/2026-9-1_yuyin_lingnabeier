# greenunion-sh Deployment Runbook

## Scope

This runbook applies only to `greenunion-sh`. It does not apply to Guangzhou or old `religion-demo` hosts.

## Stable Paths

- Current rollback baseline: `/home/ubuntu/religion_demo_v3_greenunion_app`
- Shared runtime state: `/home/ubuntu/religion_demo_shared`
- Git release checkout: `/home/ubuntu/releases/religion_demo`

## First-Time Migration

Run these commands on `greenunion-sh`.

```bash
set -euo pipefail

mkdir -p /home/ubuntu/religion_demo_shared
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/.env /home/ubuntu/religion_demo_shared/.env
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/data /home/ubuntu/religion_demo_shared/data
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/indices /home/ubuntu/religion_demo_shared/indices
mkdir -p /home/ubuntu/religion_demo_shared/logs

test -f /home/ubuntu/religion_demo_shared/.env
test -d /home/ubuntu/religion_demo_shared/data
test -d /home/ubuntu/religion_demo_shared/indices
```

## Clone Or Update Release Checkout

```bash
set -euo pipefail

mkdir -p /home/ubuntu/releases
if [ ! -d /home/ubuntu/releases/religion_demo/.git ]; then
  git clone git@github.com:675401943/20260407_-Demo-.git /home/ubuntu/releases/religion_demo
fi

cd /home/ubuntu/releases/religion_demo
git fetch --all --prune
git checkout religion-demo-20260407
git pull --ff-only
git rev-parse HEAD
```

## Deploy

By default, `docker-compose.greenunion.yml` uses:

- `GREENUNION_ENV_FILE=/home/ubuntu/religion_demo_shared/.env`
- `GREENUNION_DATA_DIR=/home/ubuntu/religion_demo_shared/data`
- `GREENUNION_INDICES_DIR=/home/ubuntu/religion_demo_shared/indices`

Override these only for local syntax checks or emergency diagnostics.

```bash
set -euo pipefail

cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml build
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml up -d
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml ps
```

## Verify

```bash
set -euo pipefail

curl -sS --max-time 10 http://127.0.0.1/healthz
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml logs --tail=120 api
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml logs --tail=120 worker
python3 - <<'PY'
import json
p='/home/ubuntu/religion_demo_shared/indices/buddhism.meta.json'
data=json.load(open(p, encoding='utf-8'))
chunks=data.get('chunks') or []
print('chunk_items', len(chunks))
print('doc_titles', len({x.get('source_title') for x in chunks if isinstance(x, dict)}))
PY
```

Expected:

```text
healthz reports api/redis/sqlite/asr/llm/tts as ok.
chunk_items is 181.
doc_titles is 65.
```

## Rollback

Rollback to a previous git commit:

```bash
set -euo pipefail

cd /home/ubuntu/releases/religion_demo
git checkout <previous_commit_sha>
cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml build
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml up -d
curl -sS --max-time 10 http://127.0.0.1/healthz
```

Emergency rollback to the old copy-based baseline:

```bash
set -euo pipefail

cd /home/ubuntu/religion_demo_v3_greenunion_app
docker compose up -d --build
curl -sS --max-time 10 http://127.0.0.1/healthz
```

## Local Compose Syntax Check

Run this from a local checkout without requiring `/home/ubuntu/religion_demo_shared` to exist:

```bash
set -euo pipefail

tmpdir="$(mktemp -d)"
touch "$tmpdir/.env"
mkdir -p "$tmpdir/data" "$tmpdir/indices"
GREENUNION_ENV_FILE="$tmpdir/.env" \
GREENUNION_DATA_DIR="$tmpdir/data" \
GREENUNION_INDICES_DIR="$tmpdir/indices" \
docker-compose -f docker-compose.greenunion.yml config >/tmp/greenunion-compose.rendered.yml
rm -rf "$tmpdir"
```
