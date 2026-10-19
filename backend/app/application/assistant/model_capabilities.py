"""Provider protocol capabilities; availability comes from the account's Models API.

Model discovery APIs do not advertise reasoning enums or built-in voice presets.
Keep those protocol rules here, shared by validation, request construction and UI.
Unknown model families use provider defaults instead of guessing reasoning values.
Sources: OpenAI Realtime conversations / latest-model; Gemini thinking / live-guide.
"""

import re
from typing import Any, Literal

Provider = Literal["openai", "gemini"]
MODEL_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,199}$")

# Appearance is a presentation choice for a synthetic character, not a claim
# about a voice actor's identity. Neutral presets use the female default.
OPENAI_VOICES = {
    "marin": "female", "cedar": "male", "alloy": "female", "ash": "male",
    "ballad": "male", "coral": "female", "echo": "male", "sage": "female",
    "shimmer": "female", "verse": "male",
}
OPENAI_LIVE_VOICES = {
    **OPENAI_VOICES, "quartz": "female", "ripple": "male", "vesper": "male",
    "willow": "female", "stone": "male", "gleam": "female", "meridian": "male",
    "bossa": "female", "tempo": "male", "beacon": "male", "delta": "female",
    "cinder": "male", "nuri": "female", "juni": "female", "flitz": "male",
    "brise": "female", "sillage": "male", "nira": "female", "harema": "female",
    "shida": "male", "noeul": "female",
}
GEMINI_VOICES = {
    "Zephyr": "female", "Puck": "male", "Charon": "male", "Kore": "female",
    "Fenrir": "male", "Leda": "female", "Orus": "male", "Aoede": "female",
    "Callirrhoe": "female", "Autonoe": "female", "Enceladus": "male", "Iapetus": "male",
    "Umbriel": "male", "Algieba": "male", "Despina": "female", "Erinome": "female",
    "Algenib": "male", "Rasalgethi": "male", "Laomedeia": "female", "Achernar": "female",
    "Alnilam": "male", "Schedar": "male", "Gacrux": "female", "Pulcherrima": "female",
    "Achird": "male", "Zubenelgenubi": "male", "Vindemiatrix": "female", "Sadachbia": "male",
    "Sadaltager": "male", "Sulafat": "female",
}


def split_model(value: str) -> tuple[Provider, str]:
    provider, _, model = value.partition(":")
    if provider not in {"openai", "gemini"} or not MODEL_ID.fullmatch(model):
        raise ValueError("Choose a model from OpenAI or Gemini.")
    if provider == "gemini" and not model.startswith("gemini-"):
        raise ValueError("Choose a Gemini model.")
    return ("gemini" if provider == "gemini" else "openai"), model


def reasoning_options(provider: str, model: str) -> list[str]:
    name = model.lower()
    if provider == "gemini":
        if "live" in name:
            if "extended-thinking" in name:
                return ["low", "medium", "high"]
            return ["minimal", "low", "medium", "high"] if "3.1" in name else []
        if name.startswith(("gemini-4-", "gemini-3.8-", "gemini-3.7-", "gemini-3.1-pro")):
            return ["low", "medium", "high"]
        if name.startswith("gemini-3-pro"):
            return ["low", "high"]
        if name.startswith("gemini-3"):
            return ["minimal", "low", "medium", "high"]
        if name.startswith("gemini-2.5"):
            return (["none"] if "pro" not in name else []) + ["low", "medium", "high"]
        return []
    if "realtime-2" in name:
        return ["low", "medium", "high"]
    if any(part in name for part in ("realtime", "audio", "live")):
        return []
    if name.startswith("gpt-5-pro"):
        return ["high"]
    if name.startswith(("gpt-5.2-pro", "gpt-5.4-pro", "gpt-5.5-pro")):
        return ["medium", "high", "xhigh"]
    if "codex" in name:
        return ["low", "medium", "high", "xhigh"] if name.startswith(("gpt-5.2", "gpt-5.3", "gpt-5.1-codex-max")) else ["low", "medium", "high"]
    if name.startswith(("gpt-6-astra", "gpt-6.1")):
        return ["low", "medium", "high", "xhigh", "max"]
    if name.startswith(("gpt-6-", "gpt-5.6")):
        return ["none", "low", "medium", "high", "xhigh", "max"]
    if name.startswith(("gpt-5.2", "gpt-5.4", "gpt-5.5")):
        return ["none", "low", "medium", "high", "xhigh"]
    if name.startswith("gpt-5.1"):
        return ["none", "low", "medium", "high"]
    if name.startswith("gpt-5"):
        return ["minimal", "low", "medium", "high"]
    if name.startswith(("o1", "o3", "o4")):
        return ["low", "medium", "high"]
    return []


def gemini_thinking(model: str, effort: str) -> dict[str, Any]:
    if not effort or effort not in reasoning_options("gemini", model):
        return {}
    if model.startswith("gemini-2.5"):
        return {"thinkingConfig": {"thinkingBudget": {"none": 0, "low": 1024, "medium": 8192, "high": 24576}[effort]}}
    return {"thinkingConfig": {"thinkingLevel": effort.upper()}}


def voice_options(provider: str, model: str) -> list[dict[str, str]]:
    voices = GEMINI_VOICES if provider == "gemini" else OPENAI_LIVE_VOICES if model.startswith("gpt-live-") else OPENAI_VOICES
    if model.startswith("gpt-4o"):
        voices = {name: appearance for name, appearance in voices.items() if name not in {"marin", "cedar"}}
    return [{"id": name, "label": name.capitalize() if provider == "openai" else name, "appearance": appearance}
            for name, appearance in voices.items()]


def voice_appearance(provider: str, voice: str) -> str:
    return (GEMINI_VOICES if provider == "gemini" else OPENAI_LIVE_VOICES).get(voice, "female")


def model_kind(provider: str, model: str, methods: list[str] | None = None) -> str | None:
    name = model.lower()
    if provider == "gemini":
        if ("live" in name or "native-audio" in name or "bidiGenerateContent" in (methods or [])) and "translate" not in name:
            return "voice"
        if any(word in name for word in ("tts", "transcribe", "embedding", "robotics", "image", "omni")):
            return None
        return "chat" if name.startswith("gemini-") and (methods is None or "generateContent" in methods) else None
    if ("realtime" in name or name.startswith("gpt-live-")) and not any(word in name for word in ("transcribe", "whisper")):
        return "voice"
    if name.startswith(("o1-mini", "o1-preview")):
        return None  # These retired models have no Responses/tool-call support.
    if any(word in name for word in ("audio", "tts", "transcribe", "image", "search", "realtime", "live", "instruct", "deep-research", "computer-use", "chat-latest")):
        return None
    return "chat" if name.startswith(("gpt-", "o1", "o3", "o4", "ft:gpt-")) else None


def model_entry(provider: str, model: str, label: str | None = None, methods: list[str] | None = None) -> dict[str, Any] | None:
    kind = model_kind(provider, model, methods)
    if kind is None or not MODEL_ID.fullmatch(model):
        return None
    return {"id": f"{provider}:{model}", "model": model, "provider": provider,
            "label": label or model, "kind": kind, "reasoning": reasoning_options(provider, model),
            "voices": voice_options(provider, model) if kind == "voice" else []}
