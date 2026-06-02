# GitAnalyse

Backend service that analyzes public GitHub user profiles, generates actionable insights, and caches results in SQLite so repeat lookups avoid unnecessary GitHub API calls.

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
