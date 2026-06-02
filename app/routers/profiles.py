from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AnalyzeRequest,
    ProfileAnalysisResponse,
    ProfileListResponse,
)
from app.services.analyzer import ProfileAnalyzerService

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _service(db: Session = Depends(get_db)) -> ProfileAnalyzerService:
    return ProfileAnalyzerService(db)


@router.post(
    "/analyze",
    response_model=ProfileAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze a GitHub username",
    description=(
        "Fetches and analyzes a GitHub profile. Returns cached results when the "
        "username was already analyzed unless `force_refresh` is true."
    ),
)
async def analyze_profile(
    body: AnalyzeRequest,
    service: ProfileAnalyzerService = Depends(_service),
) -> ProfileAnalysisResponse:
    return await service.analyze(body.username, force_refresh=body.force_refresh)


@router.get(
    "",
    response_model=ProfileListResponse,
    summary="List all analyzed profiles",
)
def list_profiles(
    service: ProfileAnalyzerService = Depends(_service),
) -> ProfileListResponse:
    profiles = service.list_all()
    return ProfileListResponse(total=len(profiles), profiles=profiles)


@router.get(
    "/{username}",
    response_model=ProfileAnalysisResponse,
    summary="Get analysis for a specific profile",
)
def get_profile(
    username: str,
    service: ProfileAnalyzerService = Depends(_service),
) -> ProfileAnalysisResponse:
    return service.get_analysis(username)
