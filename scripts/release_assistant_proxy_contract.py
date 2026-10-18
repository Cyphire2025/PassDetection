"""Exact additive voice ingress contract; every existing proxy byte must survive."""

PROXY_PATH = 'nginx/conf.d/default.conf'
ANCHOR = '    location = /api/v1/mobile/realtime {\n'
VOICE_LOCATION = """    location = /api/v1/ai-assistant/voice {
        client_max_body_size 1K;
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header Origin $http_origin;
        proxy_set_header Cookie $http_cookie;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 30s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 30s;
    }

"""


def validate_assistant_proxy(previous: str, candidate: str) -> None:
    if (previous.count(ANCHOR) != 1 or '/api/v1/ai-assistant/voice' in previous
            or candidate != previous.replace(ANCHOR, VOICE_LOCATION + ANCHOR, 1)):
        raise ValueError('assistant_proxy_must_be_exact_addition')
