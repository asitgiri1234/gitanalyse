# GitAnalyse

Backend service that analyzes public GitHub user profiles, generates actionable insights, and caches results in a database so repeat lookups avoid unnecessary GitHub API calls.

## Features

- **Cache-first analysis** — stored profiles are returned instantly without calling GitHub again
- **Rich metrics** — followers, repos, stars, account age, language breakdown, repository statistics
- **Generated insights** — tenure, impact, activity, portfolio style, and community signals
- **Graceful errors** — invalid usernames, missing users, rate limits, and API failures

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # optional: set GITHUB_TOKEN
uvicorn app.main:app --reload
```

API docs: http://127.0.0.1:8000/docs

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/profiles/analyze` | Analyze a username (uses cache unless `force_refresh`) |
| `GET` | `/api/profiles` | List all cached analyses |
| `GET` | `/api/profiles/{username}` | Get a specific cached analysis |
| `GET` | `/health` | Health check |

### Analyze a profile

```bash
curl -X POST http://127.0.0.1:8000/api/profiles/analyze \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"torvalds\"}"
```

Response includes `cached: true` when served from the database.

### Force refresh

```bash
curl -X POST http://127.0.0.1:8000/api/profiles/analyze \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"torvalds\", \"force_refresh\": true}"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | — | Personal access token (raises rate limit to 5000/hr) |
| `DATABASE_URL` | `sqlite:///./data/gitanalyse.db` | SQLAlchemy database URL |

## Deploy to Render (Web Service + PostgreSQL)

This repository includes a `render.yaml` blueprint and `Procfile` for one-click Render setup.

### 1) Push latest code to GitHub

Render deploys directly from your GitHub repository.

### 2) Create services in Render

- In Render dashboard, choose **New +** -> **Blueprint**.
- Select this repository and deploy.
- Render will provision:
  - `gitanalyse-api` (Python Web Service)
  - `gitanalyse-db` (PostgreSQL)

### 3) Set environment variables

`DATABASE_URL` is automatically wired from Render Postgres via `render.yaml`.
Set `GITHUB_TOKEN` manually in the web service environment variables:

- Key: `GITHUB_TOKEN`
- Value: your GitHub personal access token

### 4) Build/start settings (already configured)

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`

### 5) Verify deployment

- Open `https://<your-render-domain>/health` (should return `{"status":"ok"}`)
- Open `https://<your-render-domain>/`
- Search a username:
  - First run usually returns `cached: false`
  - Re-running same username should return `cached: true`
- Test invalid username and confirm friendly error message.

### Notes

- Local development can still use SQLite (`sqlite:///./data/gitanalyse.db`).
- Production should use Postgres (`DATABASE_URL` from Render).
- Never commit `.env` or token values.

## Project structure

```
app/
  main.py           # FastAPI app & error handling
  config.py         # Settings
  database.py       # SQLAlchemy engine & sessions
  models.py         # ProfileAnalysis table
  schemas.py        # Request/response models
  exceptions.py     # Domain errors
  routers/
    profiles.py     # API routes
  services/
    github.py       # GitHub API client
    analyzer.py     # Analysis & persistence logic
```
