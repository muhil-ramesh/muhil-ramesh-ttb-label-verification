# TTB Label Verification

Phase 0 scaffold for the TTB Label Verification proof of concept.

The current app is intentionally minimal: FastAPI serves a `/health` endpoint and a static frontend page that calls it.

## Local Setup

Install dependencies with Python 3.12:

```bash
uv sync --python python3.12
```

Run tests:

```bash
uv run pytest
```

Run the app locally:

```bash
uv run uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Check the health endpoint directly:

```bash
curl http://127.0.0.1:8000/health
```

## Railway Deploy

Install and authenticate the Railway CLI:

```bash
brew install railway
railway login
```

Create and link a Railway project:

```bash
railway init --name ttb-label-verification
```

Create and link an empty service for this app:

```bash
railway add --service ttb-label-verification
```

Set environment variables in Railway, not in the repo:

```bash
railway variable set APP_ENV=production
```

Confirm no local secret files are tracked:

```bash
git ls-files .env .env.local .env.production
```

That command should print nothing.

Deploy from the repo root:

```bash
railway up
```

Generate a Railway-provided public URL:

```bash
railway domain
```

Verify the deployed app:

```bash
curl https://YOUR-RAILWAY-DOMAIN.up.railway.app/health
```

Then open the domain in a browser and confirm the page shows the health response.

## Secrets

Use `.env.example` for variable names only. Real secrets must live in local `.env` files or host-managed environment variables.

Before committing, confirm no secret file is tracked:

```bash
git ls-files .env .env.local .env.production
```

That command should print nothing.
