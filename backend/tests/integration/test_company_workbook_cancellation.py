"""Request cancellation must drain native workbook work before deleting plaintext."""

import asyncio
import threading

import pytest

from app.infrastructure.travellers import company_export_workbook as assembly_owner
from app.infrastructure.travellers import company_export_worker as worker
from tests.integration.test_company_data_exports import export_fixture


@pytest.mark.parametrize("operation", ["append", "finish"])
@pytest.mark.parametrize("cancel_twice", [False, True])
async def test_cancelled_assembly_drains_native_work_before_cleanup(
    db_session,
    monkeypatch,
    operation,
    cancel_twice,
):
    context, _, _, _, storage, factory = await export_fixture(db_session)
    assert (
        await worker.run_company_export_tick(
            session_factory=factory,
            storage=storage,
            crypto=context.crypto,
        )
        == 1
    )
    identifier, token = await worker.reserve_export(factory)
    started, release, finished, close_started = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    errors = []
    original_assembly = assembly_owner.WorkbookAssembly

    def watched_assembly():
        assembly = original_assembly()
        native = getattr(assembly, operation)
        close = assembly.close

        def blocked(*args):
            started.set()
            try:
                if not release.wait(timeout=5):
                    raise AssertionError("Synthetic native worker was never released")
                return native(*args)
            except Exception as exc:
                errors.append(type(exc).__name__)
                raise
            finally:
                finished.set()

        def watched_close():
            close_started.set()
            return close()

        setattr(assembly, operation, blocked)
        assembly.close = watched_close
        return assembly

    monkeypatch.setattr(assembly_owner, "WorkbookAssembly", watched_assembly)
    task = asyncio.create_task(
        worker.assemble_workbook(factory, identifier, storage, context.crypto, token)
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        if cancel_twice:
            await asyncio.sleep(0)
            task.cancel()
        # The native worker is deliberately still holding its XML/output.
        assert not await asyncio.to_thread(close_started.wait, 0.25)
        assert not task.done()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    assert close_started.is_set()
    assert errors == []
