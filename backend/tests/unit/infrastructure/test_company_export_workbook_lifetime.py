"""Private workbook cancellation closes streaming XML before deleting its files."""

from pathlib import Path

import pytest

from app.infrastructure.travellers.company_export_render import WorkbookAssembly


@pytest.mark.parametrize("finished", [False, True])
def test_close_releases_streaming_rows_and_temp_files(finished):
    assembly = WorkbookAssembly()
    xml_path = Path(assembly.sheet._writer.out)
    directory = Path(assembly.directory.name)
    try:
        if finished:
            assert assembly.finish().startswith(b"PK")
        assembly.close()
        assert assembly.sheet.closed
        assert not xml_path.exists()
        assert not directory.exists()
    finally:
        # A failing regression must still close its real generator, rather
        # than emitting an unraisable exception in the next test's fixture.
        if not assembly.sheet.closed:
            assembly.sheet.close()
        assembly.close()
