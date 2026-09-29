import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from gc_mcp_connector.oauth import AuthorizationAttempt, CallbackServer


def test_real_loopback_callback_checks_host_state_and_replay_without_logging_secrets(capsys):
    attempt = AuthorizationAttempt.create()
    server = CallbackServer(("127.0.0.1", 0), attempt, "https://app.test")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    code = "code-with-enough-entropy-for-fixture"
    base = f"http://127.0.0.1:{server.server_port}"
    valid = "/callback?" + urlencode({"code": code, "state": attempt.state})
    try:
        with pytest.raises(HTTPError) as wrong_host:
            urlopen(Request(base + valid, headers={"Host": "attacker.test"}), timeout=3)
        assert wrong_host.value.code == 400
        with pytest.raises(HTTPError) as wrong_state:
            urlopen(base + valid.replace(attempt.state, "wrong-state"), timeout=3)
        assert wrong_state.value.code == 400
        with urlopen(base + valid, timeout=3) as response:
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert code.encode() not in response.read()
        assert server.result.get_nowait() == code
        with pytest.raises(HTTPError) as replay:
            urlopen(base + valid, timeout=3)
        assert replay.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    captured = capsys.readouterr()
    assert code not in captured.out + captured.err
    assert attempt.state not in captured.out + captured.err
