"""The dataset library's rules, tested without HTTP."""

from pathlib import Path

import pytest

from app.analytics.retail_metrics import ColumnMappingError
from app.analytics.product_performance import calculate_product_performance, resolve_performance_columns
from app.analytics.sales_trends import calculate_sales_trends, resolve_trend_columns
from app.datasets.models import AnalysisRequest, MetricsAnalysis, PerformanceAnalysis, ProfileAnalysis, TrendsAnalysis
from app.datasets.service import DatasetNotFoundError, DatasetService, display_name
from app.ingestion.csv_parser import CsvValidationError, parse_csv
from app.ingestion.profiler import profile_csv
from app.storage.file_store import StoredFileError, sha256_of

FIXTURES = Path(__file__).parent / "fixtures"
MESSY = (FIXTURES / "messy_sales.csv").read_bytes()
RENAMED = b"OrderNo,Qty,Price\nX1,2,3.00\nX2,1,4.00\n"


@pytest.fixture
def service(data_dir: Path) -> DatasetService:
    return DatasetService(data_dir, app_version="9.9.9")


def stored_files(data_dir: Path) -> list[str]:
    uploads = data_dir / "uploads"
    return sorted(path.name for path in uploads.iterdir()) if uploads.exists() else []


def test_saving_stores_the_file_and_its_metadata(service: DatasetService, data_dir: Path) -> None:
    saved = service.save_dataset("messy_sales.csv", MESSY)

    assert saved.created is True
    dataset = saved.dataset
    assert (dataset.filename, dataset.row_count, dataset.column_count, dataset.size_bytes) == ("messy_sales.csv", 6, 7, len(MESSY))
    assert dataset.columns[:3] == ["order_id", "order_date", "store"]
    assert dataset.sha256 == sha256_of(MESSY)
    assert dataset.file_stored is True
    assert stored_files(data_dir) == [f"{sha256_of(MESSY)}.csv"]


def test_identical_content_is_stored_once_even_under_another_name(service: DatasetService, data_dir: Path) -> None:
    first = service.save_dataset("messy_sales.csv", MESSY)
    second = service.save_dataset("copy of messy.csv", MESSY)

    assert second.created is False
    assert second.dataset.id == first.dataset.id
    assert second.dataset.filename == "messy_sales.csv"  # the original record is unchanged
    assert len(service.list_datasets()) == 1
    assert len(stored_files(data_dir)) == 1


def test_an_invalid_csv_is_never_stored(service: DatasetService, data_dir: Path) -> None:
    with pytest.raises(CsvValidationError):
        service.save_dataset("broken.csv", b"store,revenue\nNorth,100,extra\n")

    assert service.list_datasets() == []
    assert stored_files(data_dir) == []


def test_folder_parts_of_an_uploaded_name_are_dropped() -> None:
    assert display_name(r"C:\Users\someone\sales.csv") == "sales.csv"
    assert display_name("../../etc/sales.csv") == "sales.csv"
    assert display_name("   ") == "upload.csv"


def test_profile_analysis_is_recorded_with_the_same_result_as_live_profiling(service: DatasetService) -> None:
    dataset_id = service.save_dataset("messy_sales.csv", MESSY).dataset.id

    record = service.run_analysis(dataset_id, AnalysisRequest(kind="profile"))

    assert isinstance(record, ProfileAnalysis)
    assert record.result == profile_csv(parse_csv(MESSY))
    assert record.app_version == "9.9.9"
    assert record.column_mapping == {}
    assert service.get_analysis(dataset_id, record.id) == record


def test_metrics_analysis_records_the_column_mapping_it_used(service: DatasetService) -> None:
    dataset_id = service.save_dataset("renamed.csv", RENAMED).dataset.id
    mapping = {"order_id": "OrderNo", "quantity": "Qty", "unit_price": "Price"}

    record = service.run_analysis(dataset_id, AnalysisRequest(kind="metrics", column_mapping=mapping))

    assert isinstance(record, MetricsAnalysis)
    assert record.column_mapping == mapping
    assert record.result.total_revenue.value == 10.0
    assert record.result.columns_used["quantity"] == "Qty"


def test_trends_analysis_is_recorded_with_the_same_result_as_live_trends(service: DatasetService) -> None:
    dataset_id = service.save_dataset("messy_sales.csv", MESSY).dataset.id
    parsed = parse_csv(MESSY)

    record = service.run_analysis(dataset_id, AnalysisRequest(kind="trends", grain="week"))

    assert isinstance(record, TrendsAnalysis)
    assert record.grain == "week"
    assert record.result == calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}), "week")
    assert service.get_analysis(dataset_id, record.id) == record
    assert service.list_analyses(dataset_id)[0].highlights.model_dump() == {
        "grain": "week",
        "period_count": 1,
        "calculated_count": 3,
        "unavailable_count": 0,
    }


def test_trends_requests_default_to_months_and_reject_options_of_other_kinds() -> None:
    assert AnalysisRequest(kind="trends").grain == "month"
    assert AnalysisRequest(kind="metrics").grain is None
    with pytest.raises(ValueError, match="grain only applies to kind 'trends'"):
        AnalysisRequest(kind="metrics", grain="day")
    with pytest.raises(ValueError, match="'order_date' only applies to kind 'trends'"):
        AnalysisRequest(kind="metrics", column_mapping={"order_date": "Day"})


def test_performance_analysis_is_recorded_with_the_same_result_as_live_performance(service: DatasetService) -> None:
    catalog = (FIXTURES / "catalog_sales.csv").read_bytes()
    dataset_id = service.save_dataset("catalog_sales.csv", catalog).dataset.id
    parsed = parse_csv(catalog)

    record = service.run_analysis(dataset_id, AnalysisRequest(kind="performance"))

    assert isinstance(record, PerformanceAnalysis)
    assert record.result == calculate_product_performance(parsed, resolve_performance_columns(parsed.columns, {}))
    assert service.get_analysis(dataset_id, record.id) == record
    assert service.list_analyses(dataset_id)[0].highlights.model_dump() == {"product_count": 5, "category_count": 3}


def test_product_and_category_roles_only_apply_to_performance() -> None:
    assert AnalysisRequest(kind="performance", column_mapping={"product": "SKU", "category": "Dept"}).grain is None
    with pytest.raises(ValueError, match="'product' only applies to kind 'performance'"):
        AnalysisRequest(kind="metrics", column_mapping={"product": "SKU"})
    with pytest.raises(ValueError, match="'category' only applies to kind 'performance'"):
        AnalysisRequest(kind="trends", column_mapping={"category": "Dept"})
    with pytest.raises(ValueError, match="'order_date' only applies to kind 'trends'"):
        AnalysisRequest(kind="performance", column_mapping={"order_date": "Day"})
    with pytest.raises(ValueError, match="grain only applies to kind 'trends'"):
        AnalysisRequest(kind="performance", grain="day")


def test_an_invalid_mapping_records_nothing(service: DatasetService) -> None:
    dataset_id = service.save_dataset("renamed.csv", RENAMED).dataset.id

    with pytest.raises(ColumnMappingError):
        service.run_analysis(dataset_id, AnalysisRequest(kind="metrics", column_mapping={"quantity": "Missing"}))

    assert service.list_analyses(dataset_id) == []


def test_history_is_newest_first_with_headline_numbers(service: DatasetService) -> None:
    dataset_id = service.save_dataset("messy_sales.csv", MESSY).dataset.id
    profile = service.run_analysis(dataset_id, AnalysisRequest(kind="profile"))
    metrics = service.run_analysis(dataset_id, AnalysisRequest(kind="metrics"))

    history = service.list_analyses(dataset_id)

    assert [entry.id for entry in history] == [metrics.id, profile.id]
    assert history[0].highlights.model_dump() == {"calculated_count": 5, "unavailable_count": 0}
    assert history[1].highlights.model_dump() == {"duplicate_row_count": 1, "missing_value_count": 5, "type_mismatch_count": 3}
    summary = service.list_datasets()[0]
    assert summary.analysis_count == 2
    assert summary.last_analyzed_at == metrics.created_at


def test_deleting_removes_the_file_metadata_and_history(service: DatasetService, data_dir: Path) -> None:
    dataset_id = service.save_dataset("messy_sales.csv", MESSY).dataset.id
    service.run_analysis(dataset_id, AnalysisRequest(kind="profile"))

    service.delete_dataset(dataset_id)

    assert stored_files(data_dir) == []
    assert service.list_datasets() == []
    with pytest.raises(DatasetNotFoundError):
        service.list_analyses(dataset_id)
    with pytest.raises(DatasetNotFoundError):
        service.delete_dataset(dataset_id)


def test_ids_of_deleted_datasets_are_never_reused(service: DatasetService) -> None:
    first = service.save_dataset("messy_sales.csv", MESSY).dataset.id
    service.delete_dataset(first)

    second = service.save_dataset("renamed.csv", RENAMED).dataset.id

    assert second > first


def test_analysis_refuses_a_stored_file_that_went_missing(service: DatasetService, data_dir: Path) -> None:
    dataset = service.save_dataset("messy_sales.csv", MESSY).dataset
    (data_dir / "uploads" / f"{dataset.sha256}.csv").unlink()

    with pytest.raises(StoredFileError, match="missing"):
        service.run_analysis(dataset.id, AnalysisRequest(kind="profile"))
    assert service.get_dataset(dataset.id).file_stored is False
    assert service.list_analyses(dataset.id) == []


def test_saving_again_restores_a_missing_stored_file(service: DatasetService, data_dir: Path) -> None:
    dataset = service.save_dataset("messy_sales.csv", MESSY).dataset
    (data_dir / "uploads" / f"{dataset.sha256}.csv").unlink()

    service.delete_dataset(dataset.id)  # deleting still works without the file
    resaved = service.save_dataset("messy_sales.csv", MESSY)

    assert resaved.created is True
    assert resaved.dataset.file_stored is True


def test_unknown_dataset_is_reported(service: DatasetService) -> None:
    with pytest.raises(DatasetNotFoundError, match="Dataset 42 was not found"):
        service.get_dataset(42)
