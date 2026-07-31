from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from docx import Document


def _csv_rows(source: Path) -> list[dict[str, str]]:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _official_docx_rows(source: Path) -> list[dict[str, str]]:
    """Extract locally unambiguous hierarchical codes from the official NBS DOCX table."""
    table = Document(source).tables[0]
    rows: list[dict[str, str]] = []
    section_code = ""
    for row in table.rows[2:]:
        cells = [cell.text.strip() for cell in row.cells]
        code_columns = [
            [value.strip() for value in cell.splitlines() if value.strip()] for cell in cells[:4]
        ]
        names = [value.strip() for value in cells[4].splitlines() if value.strip()]
        code_count = sum(len(column) for column in code_columns)
        if len(names) == code_count:
            code_name_pairs = zip(
                (code for column in code_columns for code in column), names, strict=True
            )
        else:
            code_name_pairs = (
                (code, names[index])
                for column in code_columns
                for index, code in enumerate(column)
            )
        for code, name in code_name_pairs:
            if re.fullmatch(r"[A-Z]", code):
                section_code = code
            else:
                code = f"{section_code}{code}"
            if section_code:
                rows.append({"code": code, "name": name})
    return rows


def import_codes(source: Path, output: Path) -> None:
    rows = _official_docx_rows(source) if source.suffix.lower() == ".docx" else _csv_rows(source)
    records = sorted(
        {
            row["code"].strip(): {"code": row["code"].strip(), "name": row["name"].strip()}
            for row in rows
            if row["code"].strip()
        }.values(),
        key=lambda item: item["code"],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import_codes(Path(sys.argv[1]), Path(sys.argv[2]))
