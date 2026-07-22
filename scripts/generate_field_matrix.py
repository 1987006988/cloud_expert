import argparse
import csv
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.enums import CanonicalDomain
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.normalization.reports import build_field_matrix_rows, write_markdown_table


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate canonical field matrix reports.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/normalization"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for domain in (CanonicalDomain.COMPUTE.value, CanonicalDomain.OBJECT_STORAGE.value):
        rows = build_field_matrix_rows(domain)
        stem = "compute_field_matrix" if domain == "compute" else "object_storage_field_matrix"
        csv_path = args.output_dir / f"{stem}.csv"
        md_path = args.output_dir / f"{stem}.md"
        _write_csv(rows, csv_path)
        title = (
            "Compute Canonical Field Matrix"
            if domain == "compute"
            else "Object Storage Canonical Field Matrix"
        )
        write_markdown_table(rows, md_path, title=title)
        outputs.extend([str(csv_path), str(md_path)])
    print(json.dumps({"outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


def _write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    if not rows:
        atomic_write_text(output_path, "")
        return
    headers = list(rows[0])
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
