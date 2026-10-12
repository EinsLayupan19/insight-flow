"""The optional narrator: its status, and AI-written summaries of saved key findings.

Narration only works on saved insights analyses, so the server narrates findings it computed and
stored itself, never text sent by a browser. It is off unless INSIGHTS_NARRATOR is set.
"""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.datasets.service import AnalysisNotFoundError, DatasetNotFoundError
from app.narration.models import NarrationList, NarrationRecord
from app.narration.providers import Narrator, NarratorStatus, disabled_status, get_narrator
from app.narration.service import NarrationBusyError, NarrationService, NarratorUnavailableError, NotNarratableError

router = APIRouter(tags=["narration"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_narrator_dependency(settings: SettingsDep) -> Narrator | None:
    return get_narrator(settings)


NarratorDep = Annotated[Narrator | None, Depends(get_narrator_dependency)]
T = TypeVar("T")


def _call(action: Callable[[], T]) -> T:
    """Run a narration call and turn its errors into HTTP responses with the same message."""
    try:
        return action()
    except (DatasetNotFoundError, AnalysisNotFoundError) as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except NotNarratableError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except (NarratorUnavailableError, NarrationBusyError) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.get("/insights/narrator", response_model=NarratorStatus)
async def narrator_status(narrator: NarratorDep) -> NarratorStatus:
    """Whether AI summaries can be written right now, and how to enable them. Never returns URLs or keys."""
    if narrator is None:
        return disabled_status()
    return await run_in_threadpool(narrator.status)


@router.get("/datasets/{dataset_id}/analyses/{analysis_id}/narrations", response_model=NarrationList)
def list_narrations(dataset_id: int, analysis_id: int, settings: SettingsDep, narrator: NarratorDep) -> NarrationList:
    """Recorded summaries of a saved analysis, newest first."""
    service = NarrationService(settings.data_dir, narrator)
    return NarrationList(narrations=_call(lambda: service.list_narrations(dataset_id, analysis_id)))


@router.post(
    "/datasets/{dataset_id}/analyses/{analysis_id}/narrations",
    response_model=NarrationRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_narration(dataset_id: int, analysis_id: int, settings: SettingsDep, narrator: NarratorDep) -> NarrationRecord:
    """Ask the narrator to summarize saved key findings. Its text is checked; if it fails, the template summary is returned."""
    service = NarrationService(settings.data_dir, narrator)
    return await run_in_threadpool(_call, lambda: service.narrate(dataset_id, analysis_id))
