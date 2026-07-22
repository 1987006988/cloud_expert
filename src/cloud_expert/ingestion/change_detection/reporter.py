from pathlib import Path

from cloud_expert.ingestion.change_detection.models import ChangeReport
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text


def write_change_report(path: Path, report: ChangeReport) -> None:
    atomic_write_text(path, report.model_dump_json(indent=2))
