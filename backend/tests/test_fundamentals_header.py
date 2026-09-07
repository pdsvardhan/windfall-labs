"""A Trendlyne export's header row is not always row 4 (iter-172, 2026-09-07).

A CURTAILED export (subscription row cap hit) opens with
    "* The results has been curtailed to 2000 rows. Please subscribe to STRATQ..."
plus two blank rows, so the header lands on row 4. An export that fits UNDER the cap has no banner
and the header is on row 1.

_read_sheet hardcoded min_row=4, because every export the code had ever seen was curtailed - the
banner had been mistaken for part of the file format. Fed a complete export it read a DATA row as
the header, matched zero known columns and produced a snapshot of empty values. Measured on the
2026-09-07 batch: four clean band exports parsed 0 of 24 columns while the one curtailed file in
the same batch parsed 21 of 24, and the merged fill rate sat at 33% instead of ~98%.

Silent, and wrong in the worst direction: a fundamentals snapshot full of NULLs looks like "the
data source is sparse", not "the parser is broken".
"""
import openpyxl
import pytest

from windfall.data.fundamentals import _read_sheet

HEADERS = ["Stock Name", "NSE Code", "BSE Code", "Trendlyne Durability Score",
           "PE TTM Price to Earnings"]
DATA = [
    ["ABB India Ltd.", "ABB", "500002", 71, 55.2],
    ["Reliance Industries Ltd.", "RELIANCE", "500325", 62, 24.1],
    ["Tata Consultancy Services Ltd.", "TCS", "532540", 88, 26.7],
]
BANNER = "* The results has been curtailed to 2000 rows. Please subscribe to STRATQ to access 10,000 rows."


def _build(path, banner_rows: int):
    wb = openpyxl.Workbook()
    ws = wb.active
    if banner_rows:
        ws.append([BANNER])
        for _ in range(banner_rows - 1):
            ws.append([None])
    ws.append(HEADERS)
    for row in DATA:
        ws.append(row)
    wb.save(path)
    return str(path)


def test_uncurtailed_export_header_on_row_1(tmp_path):
    """The case that was silently broken."""
    hdr, rows = _read_sheet(_build(tmp_path / "clean.xlsx", banner_rows=0))
    assert hdr[:3] == ["Stock Name", "NSE Code", "BSE Code"]
    assert "Trendlyne Durability Score" in hdr
    assert len(rows) == 3
    assert {str(r[1]) for r in rows} == {"ABB", "RELIANCE", "TCS"}


def test_curtailed_export_header_on_row_4(tmp_path):
    """The case that used to work must keep working."""
    hdr, rows = _read_sheet(_build(tmp_path / "curtailed.xlsx", banner_rows=3))
    assert hdr[:3] == ["Stock Name", "NSE Code", "BSE Code"]
    assert len(rows) == 3
    assert {str(r[1]) for r in rows} == {"ABB", "RELIANCE", "TCS"}


@pytest.mark.parametrize("banner_rows", [0, 1, 2, 3, 4])
def test_header_found_wherever_the_banner_puts_it(tmp_path, banner_rows):
    """Do not re-hardcode an offset - Trendlyne can change the banner's height at will."""
    hdr, rows = _read_sheet(_build(tmp_path / f"b{banner_rows}.xlsx", banner_rows))
    assert "NSE Code" in hdr
    assert len(rows) == 3


def test_a_data_row_is_never_mistaken_for_the_header(tmp_path):
    """The precise old failure: row 4 of a clean export is ABB's data, not a header."""
    hdr, _ = _read_sheet(_build(tmp_path / "clean2.xlsx", banner_rows=0))
    assert "ABB" not in hdr, "a company code appears in the header -> a data row was read as one"
    assert "RELIANCE" not in hdr


def test_a_file_with_no_nse_code_column_fails_loudly(tmp_path):
    """Better a clear error than another snapshot of silent NULLs."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Stock Name", "Some Other Column"])
    ws.append(["ABB India Ltd.", 1])
    p = tmp_path / "wrong.xlsx"
    wb.save(p)
    with pytest.raises(ValueError, match="NSE Code"):
        _read_sheet(str(p))
