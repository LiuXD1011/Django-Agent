import io
from datetime import date, datetime, time

from .types import ParsedDocument, TextBlock


class SpreadsheetParseError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def _append_sheet_rows(document: ParsedDocument, sheet_name: str, rows):
    header_cells = None
    block_index = len(document.text_blocks)
    for row_number, cells, formula_source in rows:
        values = [_cell_text(cell.value if hasattr(cell, "value") else cell) for cell in cells]
        nonempty_columns = [index for index, value in enumerate(values) if value.strip()]
        if not nonempty_columns:
            continue
        if header_cells is None:
            header_cells = values[:]
        first_column = nonempty_columns[0]
        last_column = nonempty_columns[-1]
        metadata = {
            "sheet_name": sheet_name,
            "headers": header_cells,
            "row_start": row_number,
            "row_end": row_number,
            "column_start": first_column + 1,
            "column_end": last_column + 1,
            "formula_source": formula_source,
        }
        document.text_blocks.append(
            TextBlock(
                " | ".join(values),
                block_index,
                metadata=metadata,
                block_type="record",
                source_start=row_number,
                source_end=row_number,
            )
        )
        block_index += 1


def parse_xlsx(data: bytes) -> ParsedDocument:
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    except Exception as exc:
        raise SpreadsheetParseError("xlsx_parse_failed", "unable to read XLSX workbook") from exc

    document = ParsedDocument()
    try:
        for sheet in workbook.worksheets:
            rows = (
                (
                    row_number,
                    cells,
                    "formula" if any(cell.data_type == "f" for cell in cells) else "cached",
                )
                for row_number, cells in enumerate(sheet.iter_rows(), start=1)
            )
            _append_sheet_rows(document, sheet.title, rows)
    finally:
        workbook.close()
    return document


def parse_xls(data: bytes) -> ParsedDocument:
    try:
        import xlrd
    except ImportError as exc:
        raise SpreadsheetParseError("xls_parser_unavailable", "xlrd is required to parse XLS files") from exc

    try:
        workbook = xlrd.open_workbook(file_contents=data, on_demand=True)
    except Exception as exc:
        raise SpreadsheetParseError("xls_parse_failed", "unable to read XLS workbook") from exc

    document = ParsedDocument()
    try:
        for sheet in workbook.sheets():
            rows = (
                (row_number, sheet.row_values(row_number - 1), "cached")
                for row_number in range(1, sheet.nrows + 1)
            )
            _append_sheet_rows(document, sheet.name, rows)
    finally:
        workbook.release_resources()
    return document
