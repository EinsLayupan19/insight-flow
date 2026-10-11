"""The dataset library: save a CSV, list and view saved datasets, run analyses, and read their history.

Unlike the in-memory endpoints in uploads.py, POST /api/datasets keeps the file:
it is stored on the server's disk and its metadata and analyses in SQLite, until
the dataset is deleted. See app/datasets/service.py for what is stored where.
"""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool

from app import __version__
from app.analytics.retail_metrics import ColumnMappingError
from app.api.csv_upload import CsvFile, read_csv_upload
from app.config import Settings, get_settings
from app.datasets.models import (
    AnalysisList,
    AnalysisRecord,
    AnalysisRequest,
    DatasetDetail,
    DatasetList,
    MetricsAnalysis,
    ProfileAnalysis,
    SaveDatasetResponse,
)
from app.datasets.service import AnalysisNotFoundError, DatasetNotFoundError, DatasetService
from app.ingestion.csv_parser import CsvValidationError
from app.storage.file_store import StoredFileError

router = APIRouter(prefix="/datasets", tags=["datasets"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_dataset_service(settings: SettingsDep) -> DatasetService:
    return DatasetService(settings.data_dir, app_version=__version__)


ServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]

T = TypeVar("T")


def _call(action: Callable[[], T]) -> T:
    """Run a service call and turn its errors into HTTP responses with the same message."""
    try:
        return action()
    except (DatasetNotFoundError, AnalysisNotFoundError) as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except StoredFileError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except (CsvValidationError, ColumnMappingError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@router.post(
    "",
    response_model=SaveDatasetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": SaveDatasetResponse, "description": "The same content was already saved; nothing new was stored."}},
)
async def save_dataset(
    response: Response, settings: SettingsDep, service: ServiceDep, file: CsvFile = None
) -> SaveDatasetResponse:
    """Validate a CSV and store it in the library. Identical content is stored only once."""
    filename, content = await read_csv_upload(file, settings)
    saved = await run_in_threadpool(_call, lambda: service.save_dataset(filename, content))
    if not saved.created:
        response.status_code = status.HTTP_200_OK
    return saved


@router.get("", response_model=DatasetList)
def list_datasets(service: ServiceDep) -> DatasetList:
    """Saved datasets, newest first."""
    return DatasetList(datasets=service.list_datasets())


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: int, service: ServiceDep) -> DatasetDetail:
    return _call(lambda: service.get_dataset(dataset_id))


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: int, service: ServiceDep) -> Response:
    """Delete the stored file, the metadata, and the whole analysis history."""
    _call(lambda: service.delete_dataset(dataset_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{dataset_id}/analyses", response_model=AnalysisList)
def list_analyses(dataset_id: int, service: ServiceDep) -> AnalysisList:
    """The dataset's analysis history, newest first."""
    return AnalysisList(analyses=_call(lambda: service.list_analyses(dataset_id)))


@router.post("/{dataset_id}/analyses", response_model=AnalysisRecord, status_code=status.HTTP_201_CREATED)
async def run_analysis(
    dataset_id: int, request: AnalysisRequest, service: ServiceDep
) -> ProfileAnalysis | MetricsAnalysis:
    """Run a data-quality check ("profile") or retail metrics ("metrics") on the stored file and record it."""
    return await run_in_threadpool(_call, lambda: service.run_analysis(dataset_id, request))


@router.get("/{dataset_id}/analyses/{analysis_id}", response_model=AnalysisRecord)
def get_analysis(dataset_id: int, analysis_id: int, service: ServiceDep) -> ProfileAnalysis | MetricsAnalysis:
    """One recorded analysis, with its full result exactly as it was returned when it ran."""
    return _call(lambda: service.get_analysis(dataset_id, analysis_id))
