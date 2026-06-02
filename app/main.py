from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
