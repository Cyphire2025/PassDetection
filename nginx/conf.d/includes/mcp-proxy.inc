# The application applies a verified connection quota; this is the edge IP guard.
limit_req zone=api burst=20 nodelay;
proxy_pass http://backend;
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Request-ID $request_id;
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 120s;
proxy_connect_timeout 10s;
proxy_send_timeout 120s;
add_header Cache-Control "no-store" always;
