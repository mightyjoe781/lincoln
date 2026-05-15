# Deploying Lincoln to Render

## Prerequisites
- Render account at render.com
- GitHub repository with this code pushed

## Deploy with Blueprint (recommended)

1. Push this repository to GitHub
2. Go to render.com → New → Blueprint
3. Connect your GitHub repository
4. Render reads `render.yaml` and provisions:
   - Web service (Lincoln API, Docker runtime)
   - PostgreSQL managed database
   - Redis instance
5. After provisioning, Render runs `alembic upgrade head` automatically
   via the Dockerfile CMD before starting uvicorn
6. Your API will be live at `https://lincoln-api.onrender.com`

## Manual deploy

```bash
# Install Render CLI
npm install -g @render-com/cli

# Deploy
render deploy
```

## Environment variables set automatically
| Variable | Source |
|----------|--------|
| `DATABASE_URL` | Render managed PostgreSQL |
| `REDIS_URL` | Render managed Redis |
| `JWT_SECRET_KEY` | Auto-generated secret |

## Environment variables to set manually (if needed)
| Variable | Default | Notes |
|----------|---------|-------|
| `ENVIRONMENT` | `production` | |
| `MAX_UPLOAD_SIZE_BYTES` | `20971520` | 20 MB |

## Free tier limitations
- Web service spins down after 15 min of inactivity (cold starts ~30s)
- PostgreSQL: 1 GB storage, 97 MB RAM
- Redis: 25 MB
- Uploads volume: not persistent on free tier — use S3 adapter for production
