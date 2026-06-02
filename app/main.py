from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.database import init_db
from app.exceptions import AppError
from app.routers import profiles
from app.schemas import ErrorResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="GitAnalyse",
    description="Analyze and cache GitHub user profile insights.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(profiles.router)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            detail=exc.message,
            error_code=exc.error_code,
            extra=exc.extra or None,
        ).model_dump(),
    )


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


_INLINE_ROOT_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>GitAnalyse</title>
  </head>
  <body style="font-family: Arial, sans-serif; margin: 2rem;">
    <h1>GitAnalyse API is live</h1>
    <p>If the rich UI could not be loaded, use these endpoints directly:</p>
    <ul>
      <li><a href="/docs">/docs</a></li>
      <li><a href="/health">/health</a></li>
      <li><code>POST /api/profiles/analyze</code></li>
      <li><code>GET /api/profiles/{username}</code></li>
    </ul>
  </body>
</html>
"""


@app.get("/", include_in_schema=False)
def root() -> Response:
    # Render an HTML UI if present; otherwise provide an inline fallback page.
    ui_path = Path(__file__).resolve().parent / "ui" / "index.html"
    if ui_path.exists():
        return FileResponse(ui_path)
    return HTMLResponse(content=_INLINE_ROOT_HTML, status_code=200)


@app.get("/index.html", include_in_schema=False)
def root_index() -> Response:
    return root()
