"""Real Celery tracing with a real synthetic DB error and a memory result backend."""

from __future__ import annotations

import json
import logging
import pickle
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from billiard.einfo import ExceptionInfo
from celery import Celery, states
from celery.app.trace import build_tracer
from celery.backends.cache import CacheBackend
from celery.backends.redis import RedisBackend
from celery.exceptions import Ignore, Reject, Retry
from celery.worker.consumer.consumer import Consumer
from celery.worker.strategy import default as default_strategy
from kombu import Message
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.logging.celery_diagnostics import install_celery_diagnostic_filters
from app.core.logging.task_diagnostics import PRIVATE_ARGUMENTS
from app.infrastructure.ai_priority.runtime import AiPriorityAdmissionDeferred
from app.infrastructure.processing.private_result_backend import (
    PrivateRedisBackend,
    PrivateResultBackendMixin,
)
from app.infrastructure.processing.private_task import PrivateTask
from app.infrastructure.processing.private_task_request import PrivateTaskRequest
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError

DETAIL = "synthetic-private-DB-detail-P1234567"
BOUND = "synthetic-bound-passport-P7654321"
PAYLOAD = "synthetic-private-passport-link-token"


class MemoryPrivateBackend(PrivateResultBackendMixin, CacheBackend):
    pass


@pytest.fixture
def private_celery():
    app = Celery(
        "isolated-diagnostic-tests", broker="memory://", set_as_current=False, task_cls=PrivateTask
    )
    app.conf.update(task_store_eager_result=True, task_eager_propagates=False)
    app._backend = MemoryPrivateBackend(app=app, backend="memory")
    install_celery_diagnostic_filters()
    yield app
    app.close()


@pytest.fixture
def database_error():
    engine = create_engine("sqlite://", hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE TABLE synthetic_passenger (passport TEXT)"))
            connection.execute(
                text(
                    "CREATE TRIGGER reject_synthetic BEFORE INSERT ON synthetic_passenger "
                    "BEGIN SELECT RAISE(ABORT, '" + DETAIL + "'); END"
                )
            )
            with pytest.raises(IntegrityError) as failure:
                connection.execute(
                    text("INSERT INTO synthetic_passenger VALUES (:passport)"), {"passport": BOUND}
                )
        return failure.value
    finally:
        engine.dispose()


def assert_private_metadata(metadata):
    assert DETAIL not in str(metadata["result"])
    assert DETAIL not in (metadata.get("traceback") or "")
    assert BOUND not in str(metadata)
    assert "IntegrityError" in str(metadata["result"])


def test_terminal_failure_projects_before_storage_and_automatic_logging(
    private_celery, database_error, caplog
):
    seen = []

    @private_celery.task(name="synthetic.private.failure")
    def fail(*, passenger_link):
        seen.append(passenger_link)
        raise database_error

    original_args = database_error.args
    with caplog.at_level(logging.INFO, logger="celery.app.trace"):
        result = fail.apply(kwargs={"passenger_link": PAYLOAD}, throw=False)

    metadata = private_celery.backend.get_task_meta(result.id)
    assert result.state == metadata["status"] == states.FAILURE
    assert seen == [PAYLOAD]
    assert isinstance(result.result, IntegrityError)
    assert database_error.args == original_args
    assert DETAIL in str(database_error) and BOUND not in str(database_error)
    assert_private_metadata(metadata)
    records = [record for record in caplog.records if record.name == "celery.app.trace"]
    assert records
    for record in records:
        assert DETAIL not in logging.Formatter().format(record)
        assert PAYLOAD not in str(record.__dict__)
        assert DETAIL not in str(getattr(record, "data", {}))


def test_worker_like_retry_retains_payload_countdown_and_retry_status(
    private_celery, database_error, monkeypatch, caplog
):
    @private_celery.task(bind=True, name="synthetic.private.retry", max_retries=2)
    def retry(self, *, passenger_link):
        assert passenger_link == PAYLOAD
        try:
            raise database_error
        except IntegrityError as exc:
            raise self.retry(exc=exc, countdown=7)

    published = Mock(return_value=SimpleNamespace(id="synthetic-retry"))
    monkeypatch.setattr(private_celery, "send_task", published)
    task_id = str(uuid.uuid4())
    request = {
        "id": task_id,
        "task": retry.name,
        "retries": 0,
        "is_eager": False,
        "hostname": "synthetic-worker",
        "delivery_info": {"exchange": "", "routing_key": "whatsapp"},
    }
    tracer = build_tracer(retry.name, retry, eager=False, app=private_celery)
    with caplog.at_level(logging.INFO, logger="celery.app.trace"):
        traced = tracer(task_id, (), {"passenger_link": PAYLOAD}, request)

    assert traced.info.state == states.RETRY
    assert isinstance(traced.info.retval, Retry)
    assert isinstance(traced.info.retval.exc, IntegrityError)
    metadata = private_celery.backend.get_task_meta(task_id)
    assert metadata["status"] == states.RETRY
    assert_private_metadata(metadata)
    published.assert_called_once()
    call = published.call_args
    assert call.args[2] == {"passenger_link": PAYLOAD}
    assert call.kwargs["countdown"] == 7
    assert call.kwargs["retries"] == 1
    assert call.kwargs["argsrepr"] == call.kwargs["kwargsrepr"] == PRIVATE_ARGUMENTS
    assert DETAIL not in caplog.text


@pytest.mark.parametrize("legacy", [True, False])
def test_request_masks_received_representations_before_task_start(private_celery, legacy):
    @private_celery.task(name="synthetic.private.received")
    def task(*, passenger_link):
        return passenger_link

    headers = {"id": str(uuid.uuid4()), "task": task.name}
    if not legacy:
        headers.update(argsrepr=PAYLOAD, kwargsrepr=PAYLOAD)
    body = ((), {"passenger_link": PAYLOAD}, {})
    message = Message(body=body, headers=headers)
    request = PrivateTaskRequest(message, app=private_celery, task=task, decoded=True, body=body)

    assert request.kwargs == {"passenger_link": PAYLOAD}
    assert request.argsrepr == request.kwargsrepr == PRIVATE_ARGUMENTS
    assert PAYLOAD not in str(request.info(safe=True))
    assert headers.get("kwargsrepr") == (None if legacy else PAYLOAD)


def test_early_worker_failure_event_and_metadata_are_private(private_celery, database_error):
    @private_celery.task(name="synthetic.private.early-failure")
    def task(*, passenger_link):
        raise AssertionError("Task body should not run")

    eventer = SimpleNamespace(enabled=True, send=Mock())
    body = ((), {"passenger_link": PAYLOAD}, {})
    message = Message(body=body, headers={"id": str(uuid.uuid4()), "task": task.name})
    request = PrivateTaskRequest(
        message,
        app=private_celery,
        task=task,
        decoded=True,
        body=body,
        eventer=eventer,
        on_ack=Mock(),
        on_reject=Mock(),
    )
    try:
        raise database_error
    except IntegrityError:
        error_info = ExceptionInfo()
    request.on_failure(error_info)

    metadata = private_celery.backend.get_task_meta(request.id)
    assert metadata["status"] == states.FAILURE
    assert_private_metadata(metadata)
    assert eventer.send.called
    assert DETAIL not in str(eventer.send.call_args_list)
    assert PAYLOAD not in str(eventer.send.call_args_list)
    assert request.kwargs == {"passenger_link": PAYLOAD}


def test_known_provider_code_and_successful_business_result_survive(private_celery):
    error = WhatsAppCloudApiError(DETAIL, code="WHATSAPP_PROVIDER_RATE_LIMITED", transient=True)
    task_id = str(uuid.uuid4())
    private_celery.backend.mark_as_failure(task_id, error)
    metadata = private_celery.backend.get_task_meta(task_id)
    assert metadata["status"] == states.FAILURE
    assert "WHATSAPP_PROVIDER_RATE_LIMITED" in str(metadata["result"])
    assert DETAIL not in str(metadata["result"])
    assert error.transient

    @private_celery.task(name="synthetic.private.success")
    def succeed(*, passenger_link):
        return {"business_value": passenger_link}

    result = succeed.apply(kwargs={"passenger_link": PAYLOAD})
    stored = private_celery.backend.get_task_meta(result.id)
    assert result.state == stored["status"] == states.SUCCESS
    assert result.result == stored["result"] == {"business_value": PAYLOAD}


def test_publication_masks_headers_without_replacing_actual_payload(private_celery, monkeypatch):
    @private_celery.task(name="synthetic.private.publish")
    def task(*, passenger_link):
        return passenger_link

    publish = Mock(return_value=SimpleNamespace(id="synthetic"))
    monkeypatch.setattr(private_celery, "send_task", publish)
    task.apply_async(kwargs={"passenger_link": PAYLOAD}, kwargsrepr=PAYLOAD, argsrepr=PAYLOAD)

    assert publish.call_args.args[2] == {"passenger_link": PAYLOAD}
    assert publish.call_args.kwargs["kwargsrepr"] == PRIVATE_ARGUMENTS
    assert publish.call_args.kwargs["argsrepr"] == PRIVATE_ARGUMENTS


@pytest.mark.parametrize("legacy", [True, False])
def test_actual_received_strategy_event_never_exposes_old_headers(private_celery, legacy, caplog):
    @private_celery.task(name="synthetic.private.strategy", send_events=True)
    def task(*, passenger_link):
        raise AssertionError("Consumer must not execute the task")

    eventer = SimpleNamespace(enabled=True, send=Mock())
    consumer = Mock()
    consumer.hostname = "synthetic-worker"
    consumer.connection_errors = ()
    consumer.event_dispatcher = eventer
    consumer.disable_rate_limits = True
    consumer.task_buckets = {}
    consumer.controller.state.revoked = set()
    headers = {"id": str(uuid.uuid4()), "task": task.name}
    if not legacy:
        headers.update(argsrepr=PAYLOAD, kwargsrepr=PAYLOAD)
    body = [[], {"passenger_link": PAYLOAD}, {}]
    message = Message(
        body=json.dumps(body),
        headers=headers,
        content_type="application/json",
        content_encoding="utf-8",
    )
    with caplog.at_level(logging.INFO, logger="celery.worker.strategy"):
        handler = default_strategy(task, private_celery, consumer)
        handler(message, None, Mock(), Mock(), [])

    request = consumer.on_task_request.call_args.args[0]
    assert request.kwargs == {"passenger_link": PAYLOAD}
    events = [call for call in eventer.send.call_args_list if call.args[0] == "task-received"]
    assert len(events) == 1
    assert events[0].kwargs["args"] == events[0].kwargs["kwargs"] == PRIVATE_ARGUMENTS
    assert PAYLOAD not in str(eventer.send.call_args_list)
    assert PAYLOAD not in str([record.__dict__ for record in caplog.records])
    request.on_success((False, {"business_value": PAYLOAD}, 0.5))
    completed = eventer.send.call_args
    assert completed.args[0] == "task-succeeded"
    assert completed.kwargs["result"] == "<private task result>"
    assert PAYLOAD not in str(completed)


def test_early_worker_retry_event_preserves_retry_status_without_private_detail(
    private_celery, database_error
):
    @private_celery.task(name="synthetic.private.early-retry")
    def task(*, passenger_link):
        raise AssertionError("Task body should not run")

    eventer = SimpleNamespace(enabled=True, send=Mock())
    body = ((), {"passenger_link": PAYLOAD}, {})
    message = Message(body=body, headers={"id": str(uuid.uuid4()), "task": task.name})
    request = PrivateTaskRequest(
        message,
        app=private_celery,
        task=task,
        decoded=True,
        body=body,
        eventer=eventer,
        on_ack=Mock(),
        on_reject=Mock(),
    )
    try:
        raise Retry(exc=database_error, when=7)
    except Retry:
        error_info = ExceptionInfo()
    request.on_retry(error_info)

    assert eventer.send.call_args.args[0] == "task-retried"
    assert DETAIL not in str(eventer.send.call_args)
    assert "IntegrityError" in str(eventer.send.call_args)
    assert request.kwargs == {"passenger_link": PAYLOAD}


def test_unknown_message_before_request_construction_does_not_dump_private_body(caplog):
    body = {"unexpected_format": PAYLOAD}
    message = Message(
        body=json.dumps(body),
        headers={},
        content_type="application/json",
        content_encoding="utf-8",
    )
    message.reject_log_error = Mock()
    consumer = SimpleNamespace(connection_errors=())
    consumer._message_report = lambda payload, msg: Consumer._message_report(consumer, payload, msg)
    with caplog.at_level(logging.WARNING, logger="celery.worker.consumer.consumer"):
        Consumer.on_unknown_message(consumer, body, message)

    message.reject_log_error.assert_called_once()
    assert PAYLOAD not in caplog.text
    assert PAYLOAD not in str([record.__dict__ for record in caplog.records])


@pytest.mark.parametrize("control", ["ignore", "reject"])
def test_control_flow_exceptions_keep_their_original_worker_classification(private_celery, control):
    @private_celery.task(name=f"synthetic.private.{control}")
    def task():
        if control == "ignore":
            raise Ignore(PAYLOAD)
        raise Reject(PAYLOAD, requeue=True)

    result = task.apply(throw=False)
    assert result.state == (states.IGNORED if control == "ignore" else states.REJECTED)
    assert isinstance(result.result, Ignore if control == "ignore" else Reject)
    if control == "reject":
        assert result.result.requeue is True
    assert private_celery.backend.get_task_meta(result.id)["status"] == states.PENDING


def test_production_private_backend_binding_survives_app_serialization():
    from app.infrastructure.processing.celery_app import celery_app

    restored = pickle.loads(pickle.dumps(celery_app))
    try:
        assert isinstance(celery_app.backend, PrivateRedisBackend)
        assert isinstance(restored.backend, PrivateRedisBackend)
        assert restored.backend.url == celery_app.backend.url
        assert restored.conf.result_backend == celery_app.conf.result_backend
        assert restored.conf.broker_url == celery_app.conf.broker_url
    finally:
        restored.close()


def test_actual_admission_autoretry_keeps_decision_exception_and_payload(
    private_celery, monkeypatch
):
    admission = AiPriorityAdmissionDeferred(
        workload="synthetic", reason=DETAIL, retry_after_ms=1200
    )

    @private_celery.task(
        name="synthetic.private.admission",
        autoretry_for=(AiPriorityAdmissionDeferred,),
        retry_kwargs={"max_retries": 2, "countdown": 3},
    )
    def task(*, passenger_link):
        assert passenger_link == PAYLOAD
        raise admission

    publish = Mock(return_value=SimpleNamespace(id="synthetic-admission-retry"))
    monkeypatch.setattr(private_celery, "send_task", publish)
    task_id = str(uuid.uuid4())
    tracer = build_tracer(task.name, task, eager=False, app=private_celery)
    traced = tracer(
        task_id,
        (),
        {"passenger_link": PAYLOAD},
        {
            "id": task_id,
            "task": task.name,
            "retries": 0,
            "is_eager": False,
            "delivery_info": {"exchange": "", "routing_key": "whatsapp"},
        },
    )

    assert traced.info.state == states.RETRY
    # Celery itself converts this keyword-only exception to its pickleable
    # RuntimeError parent. Match that existing reporting behavior; the original
    # typed admission decision still selected autoretry inside the task.
    baseline_report = Retry(exc=admission).exc
    assert type(traced.info.retval.exc) is type(baseline_report)
    assert traced.info.retval.exc.args == baseline_report.args
    assert admission.retry_after_ms == 1200
    assert publish.call_args.args[2] == {"passenger_link": PAYLOAD}
    assert publish.call_args.kwargs["countdown"] == 3
    assert DETAIL not in str(private_celery.backend.get_task_meta(task_id))


@pytest.mark.parametrize(
    "url",
    [
        "redis://:synthetic-password@127.0.0.1:6379/2",
        "rediss://:synthetic-password@127.0.0.1:6380/3?ssl_cert_reqs=required",
    ],
)
def test_private_backend_preserves_existing_redis_connection_and_tls_parameters(
    private_celery, url
):
    original = RedisBackend(app=private_celery, url=url)
    projected = PrivateRedisBackend(app=private_celery, url=url)

    assert projected.url == original.url
    assert projected.connparams == original.connparams
    assert projected.expires == original.expires
    assert projected.serializer == original.serializer
