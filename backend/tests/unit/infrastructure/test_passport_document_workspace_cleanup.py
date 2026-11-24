"""Every staged native spool is closed even when one close callback reports failure."""

from __future__ import annotations

import pytest

from app.infrastructure.imports import passport_document_importer as importer
from app.infrastructure.security.upload_validator import ValidatedUpload


@pytest.mark.parametrize("failures", [(), (0,), (1,), (0, 2)])
def test_workspace_drains_all_actual_disk_spools_and_preserves_first_close_error(
    monkeypatch, failures
):
    real_factory = importer.tempfile.SpooledTemporaryFile
    streams = []
    errors = {index: OSError(f"synthetic close failure {index}") for index in failures}

    class CloseProtocol:
        def __init__(self, stream, index):
            self.stream = stream
            self.index = index
            self.calls = 0

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            self.calls += 1
            self.stream.close()
            if self.index in errors:
                raise errors[self.index]

    def factory(*args, **kwargs):
        value = CloseProtocol(real_factory(*args, **kwargs), len(streams))
        streams.append(value)
        return value

    monkeypatch.setattr(importer.tempfile, "SpooledTemporaryFile", factory)
    workspace = importer.PassportDocumentImportWorkspace()
    try:
        for index in range(3):
            workspace.stage(
                ValidatedUpload(
                    content=b"synthetic canonical image" * 4000,
                    content_type="image/jpeg",
                    filename=f"synthetic-{index}.jpg",
                    width=10,
                    height=10,
                    format="JPEG",
                )
            )
        assert all(stream.stream._rolled for stream in streams)
        assert workspace.staged_bytes > 3 * importer.PASSPORT_DOCUMENT_SPOOL_MEMORY_BYTES
        if failures:
            with pytest.raises(OSError) as error:
                workspace.close()
            assert error.value is errors[min(failures)]
        else:
            workspace.close()
        assert all(stream.stream.closed for stream in streams)
        assert [stream.calls for stream in streams] == [1, 1, 1]
        assert workspace.staged_bytes == 0
        workspace.close()
        assert [stream.calls for stream in streams] == [1, 1, 1]
    finally:
        for stream in streams:
            stream.stream.close()
