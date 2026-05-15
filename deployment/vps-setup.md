# Lincoln — VPS Deployment Guide

Assumes: Ubuntu/Debian VPS, Docker + Docker Compose installed, nginx running, your monitoring stack (Prometheus + Grafana + Loki + Alloy) already up.

---

## Directory Layout on VPS

```
/opt/lincoln/
├── .env                          # secrets — never commit this
├── deployment/
│   ├── docker-compose.vps.yml    # the compose file to use
│   └── prometheus-scrape.yml     # scrape job to add to prometheus.yml
```

---

## Step 1 — Clone the Repo

```bash
git clone https://github.com/mightyjoe781/lincoln.git /opt/lincoln
cd /opt/lincoln
```

---

## Step 2 — Create `.env`

The `.env` file lives at the **project root** (`/opt/lincoln/.env`), one level above `deployment/`. The compose file references it as `env_file: ../.env`.

```bash
cp .env.example .env
nano .env
```

Minimum values to set:

```env
# ── Database ─────────────────────────────────────────────────────────────────
# These must match POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB below
DATABASE_URL=postgresql+asyncpg://lincoln:<STRONG_DB_PASSWORD>@lincoln-db:5432/lincoln

# ── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL=redis://lincoln-redis:6379/0

# ── File storage ─────────────────────────────────────────────────────────────
UPLOAD_DIR=/uploads
MAX_UPLOAD_SIZE_BYTES=20971520

# ── JWT ──────────────────────────────────────────────────────────────────────
# Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=<GENERATED_SECRET>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# ── Admin seed user ──────────────────────────────────────────────────────────
ADMIN_EMAIL=admin@sudomoon.com
ADMIN_PASSWORD=<STRONG_ADMIN_PASSWORD>

# ── Registration gate ────────────────────────────────────────────────────────
# Generate: python3 -c "import secrets; print(secrets.token_hex(16))"
REGISTRATION_TOKEN=<GENERATED_TOKEN>

# ── Postgres credentials (used by lincoln-db service) ────────────────────────
POSTGRES_USER=lincoln
POSTGRES_PASSWORD=<STRONG_DB_PASSWORD>   # must match DATABASE_URL above
POSTGRES_DB=lincoln

# ── Runtime ──────────────────────────────────────────────────────────────────
ENVIRONMENT=production
HOST_NAME=sudomoon-vps             # used in Prometheus/Grafana labels
```

Set restrictive permissions — this file contains secrets:

```bash
chmod 600 /opt/lincoln/.env
```

---

## Step 3 — Build the Image

```bash
cd /opt/lincoln
docker build -t lincoln:latest .
```

---

## Step 4 — Start Lincoln

```bash
docker compose -f /opt/lincoln/deployment/docker-compose.vps.yml up -d
```

Check startup logs (migrations + seed run before uvicorn):

```bash
docker logs lincoln-app --follow
# expect:
#   INFO [alembic] Running upgrade ...
#   Created admin user: admin@sudomoon.com
#   INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## Step 5 — Nginx Config

Add a new site config (or a server block in your existing nginx conf):

```nginx
server {
    listen 80;
    server_name lincoln.sudomoon.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name lincoln.sudomoon.com;

    # SSL — adjust paths to your cert (e.g. Let's Encrypt)
    ssl_certificate     /etc/letsencrypt/live/lincoln.sudomoon.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lincoln.sudomoon.com/privkey.pem;

    client_max_body_size 25M;   # slightly above MAX_UPLOAD_SIZE_BYTES

    location / {
        proxy_pass         http://127.0.0.1:13006;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;   # uploads can take a moment
    }
}
```

```bash
nginx -t && systemctl reload nginx
```

---

## Step 6 — Wire Prometheus

Add the Lincoln scrape job to your existing `prometheus/prometheus.yml`:

```yaml
  - job_name: lincoln
    static_configs:
      - targets: ["lincoln-app:8000"]
    metrics_path: /metrics
    scrape_interval: 15s
    labels:
      host: "sudomoon-vps"
      service: lincoln
```

Reload Prometheus (no restart needed):

```bash
curl -s -X POST http://localhost:9090/-/reload
```

Verify in Grafana → Explore → Prometheus → `up{job="lincoln"}` should return `1`.

---

## Step 7 — Verify Loki Logs

Alloy already discovers all Docker containers via the socket. Lincoln logs appear automatically in Loki with these labels:

```
container = "lincoln-app"      # or lincoln-worker, lincoln-db, lincoln-redis
job       = "integrations/docker"
stream    = "stdout"
```

In Grafana → Explore → Loki:

```logql
{container="lincoln-app"} | json
```

---

## Useful Commands

```bash
# Tail live logs
docker logs lincoln-app -f
docker logs lincoln-worker -f

# Restart a service (e.g. after .env change)
docker compose -f /opt/lincoln/deployment/docker-compose.vps.yml restart lincoln-app

# Pull latest code and redeploy
cd /opt/lincoln
git pull
docker build -t lincoln:latest .
docker compose -f /opt/lincoln/deployment/docker-compose.vps.yml up -d --no-deps lincoln-app lincoln-worker

# Run a one-off migration (if needed outside normal boot)
docker exec lincoln-app alembic upgrade head

# Open a psql shell
docker exec -it lincoln-db psql -U lincoln -d lincoln

# Stop everything
docker compose -f /opt/lincoln/deployment/docker-compose.vps.yml down

# Full teardown including volumes (DESTRUCTIVE — deletes all data)
docker compose -f /opt/lincoln/deployment/docker-compose.vps.yml down -v
```

---

## Updating Lincoln

```bash
cd /opt/lincoln
git pull
docker build -t lincoln:latest .

# Rolling restart — DB and Redis stay up, only app + worker restart
docker compose -f /opt/lincoln/deployment/docker-compose.vps.yml up -d --no-deps lincoln-app lincoln-worker
```

Migrations run automatically on `lincoln-app` startup before uvicorn starts.
