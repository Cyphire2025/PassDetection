"""Security contracts exercised through the actual locked dependency consumers."""

import ssl

import certifi
import pytest
from mcp.shared._otel import extract_trace_context
from opentelemetry.trace import get_current_span

TRACE_PARENT = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"


def test_mcp_trace_context_drops_oversized_state_without_discarding_parent() -> None:
    # Every member is individually valid; only their aggregate exceeds 8 KiB.
    # The vulnerable parser accepted this instead of bounding parsing work.
    state = ",".join(f"v{index}=" + "a" * 256 for index in range(32))
    assert len(state) > 8192
    context = extract_trace_context({"traceparent": TRACE_PARENT, "tracestate": state})
    assert context is not None
    span = get_current_span(context).get_span_context()
    assert span.is_valid
    assert span.trace_id == int("0123456789abcdef0123456789abcdef", 16)
    assert not span.trace_state


@pytest.mark.parametrize("whitespace", [" ", "\t"])
def test_mcp_trace_state_bounds_optional_whitespace(whitespace: str) -> None:
    context = extract_trace_context({
        "traceparent": TRACE_PARENT, "tracestate": "vendor=ok," + whitespace * 8193,
    })
    assert context is not None
    assert not get_current_span(context).get_span_context().trace_state


def test_mcp_preserves_legitimate_trace_context() -> None:
    context = extract_trace_context({
        "traceparent": TRACE_PARENT, "tracestate": "vendor=ok,other=value",
    })
    assert context is not None
    span = get_current_span(context).get_span_context()
    assert span.is_valid
    assert list(span.trace_state.items()) == [("vendor", "ok"), ("other", "value")]


def test_outbound_tls_bundle_excludes_compromised_emsign_root() -> None:
    # Load exactly the bundle used by HTTP clients, without platform CA additions.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    roots = context.get_ca_certs()
    assert roots  # The mitigation must preserve normal TLS certificate validation.
    common_names = {
        value for certificate in roots for rdn in certificate["subject"]
        for key, value in rdn if key == "commonName"
    }
    assert "emSign ECC Root CA - G3" not in common_names
