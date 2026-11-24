"""Audio boundary diagnostics must distinguish silence without retaining content."""

import base64
import struct

from app.presentation.assistant.voice_diagnostics import VoiceStreamDiagnostics


def test_voice_diagnostics_distinguish_silence_and_output_without_content():
    diagnostics = VoiceStreamDiagnostics()
    diagnostics.input(bytes(3200))
    diagnostics.input(struct.pack("<1600h", *([2000, -2000] * 800)))
    diagnostics.sent({"type": "text_delta", "text": "private caption"})
    diagnostics.sent({"type": "audio", "data": base64.b64encode(bytes(4800)).decode()})
    result = diagnostics.summary()
    assert result["input_frames"] == 2
    assert result["non_silent_input_frames"] == 1
    assert result["input_audio_ms"] == 200
    assert result["input_peak"] == 0.061
    assert result["output_frames"] == 1
    assert result["output_audio_ms"] == 100
    assert result["first_output_ms"] is not None
    assert all(value is None or isinstance(value, (int, float)) for value in result.values())
    assert "private caption" not in str(vars(diagnostics))
    assert not any(isinstance(value, (bytes, str)) for value in vars(diagnostics).values())


def test_voice_diagnostics_do_not_report_a_response_for_caption_only():
    diagnostics = VoiceStreamDiagnostics()
    diagnostics.sent({"type": "text_delta", "text": "A silent reply"})
    diagnostics.sent({"type": "audio", "data": None})
    assert diagnostics.summary()["output_frames"] == 0
    assert diagnostics.summary()["first_output_ms"] is None
