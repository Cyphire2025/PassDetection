"""Optional Gemini voice-library discovery, including provider presentation metadata."""


import httpx

from app.application.assistant.model_capabilities import MODEL_ID, voice_options


async def gemini_voices(client: httpx.AsyncClient) -> list[dict[str, str]]:
    voices = {voice["id"]: voice for voice in voice_options("gemini", "")}
    params: dict[str, str | int] = {"page_size": 1000}
    seen: set[str] = set()
    try:
        for _ in range(20):
            response = await client.get("/voices", params=params)
            if response.status_code != 200 or len(response.content) > 4 * 1024 * 1024:
                break
            data = response.json()
            rows = data.get("voices", [])
            if not isinstance(rows, list):
                break
            for row in rows:
                identifier = row.get("id", "")
                if not isinstance(identifier, str) or len(identifier) > 100 or not MODEL_ID.fullmatch(identifier):
                    continue
                label = row.get("display_name", row.get("displayName", identifier))
                voices[identifier] = {"id": identifier, "label": str(label)[:120],
                                      "appearance": "male" if row.get("gender") == "male" else "female"}
            token = data.get("next_page_token", data.get("nextPageToken"))
            if not token or not isinstance(token, str) or token in seen:
                break
            seen.add(token)
            params["page_token"] = token
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        pass  # Older projects may only expose the documented studio presets.
    return list(voices.values())
