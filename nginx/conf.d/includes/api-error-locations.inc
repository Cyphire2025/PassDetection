# No URI, query string, body, upstream address or exception is reflected.

location @api_error_400 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 400 '{"error":{"code":"BAD_REQUEST","message":"Malformed request"}}';
}


location @api_error_413 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 413 '{"error":{"code":"PAYLOAD_TOO_LARGE","message":"Request body exceeds the route limit"}}';
}

location @api_error_414 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 414 '{"error":{"code":"URI_TOO_LONG","message":"Request URI exceeds the limit"}}';
}

location @api_error_431 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 431 '{"error":{"code":"REQUEST_HEADER_FIELDS_TOO_LARGE","message":"Request headers exceed the limit"}}';
}

location @api_error_500 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 500 '{"error":{"code":"INTERNAL_SERVER_ERROR","message":"An unexpected server error occurred"}}';
}

location @api_error_502 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 502 '{"error":{"code":"BAD_GATEWAY","message":"The application is temporarily unavailable"}}';
}

location @api_error_503 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 503 '{"error":{"code":"SERVICE_UNAVAILABLE","message":"The application is temporarily unavailable"}}';
}

location @api_error_504 {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Request-ID $request_id always;
    return 504 '{"error":{"code":"GATEWAY_TIMEOUT","message":"The application did not respond in time"}}';
}
