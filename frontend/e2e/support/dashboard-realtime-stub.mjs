import { createHash } from "node:crypto";
import { createServer } from "node:http";

const host = "127.0.0.1";
const port = Number.parseInt(process.argv[2] ?? "", 10);
const realtimePath = "/api/v1/dashboard/realtime";
const webSocketGuid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const sockets = new Set();

if (!Number.isSafeInteger(port) || port < 1_024 || port > 65_535) {
  throw new Error("The isolated realtime stub requires an explicit non-privileged port");
}

const server = createServer((request, response) => {
  if (request.method === "GET" && request.url === "/health") {
    response.writeHead(200, {
      "cache-control": "no-store",
      "content-type": "application/json",
    });
    response.end('{"status":"ready"}');
    return;
  }
  response.writeHead(404, { "content-type": "application/json" });
  response.end('{"error":"not_found"}');
});

server.on("upgrade", (request, socket) => {
  const requestUrl = new URL(request.url ?? "/", `http://${host}:${port}`);
  const key = request.headers["sec-websocket-key"];
  if (
    requestUrl.pathname !== realtimePath
    || typeof key !== "string"
    || request.headers.upgrade?.toLowerCase() !== "websocket"
  ) {
    socket.end("HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n");
    return;
  }

  const accept = createHash("sha1")
    .update(`${key}${webSocketGuid}`)
    .digest("base64");
  socket.write([
    "HTTP/1.1 101 Switching Protocols",
    "Upgrade: websocket",
    "Connection: Upgrade",
    `Sec-WebSocket-Accept: ${accept}`,
    "\r\n",
  ].join("\r\n"));
  sockets.add(socket);
  socket.write(textFrame(JSON.stringify({
    type: "ready",
    heartbeat_seconds: 10,
    idle_timeout_seconds: 45,
  })));

  const heartbeat = setInterval(() => {
    if (!socket.destroyed) {
      socket.write(textFrame('{"type":"heartbeat"}'));
    }
  }, 10_000);
  heartbeat.unref();

  const finish = () => {
    clearInterval(heartbeat);
    sockets.delete(socket);
  };
  socket.on("data", (chunk) => {
    if (chunk.length > 0 && (chunk[0] & 0x0f) === 0x08) {
      socket.end(Buffer.from([0x88, 0x00]));
    }
  });
  socket.once("close", finish);
  socket.once("error", finish);
});

function textFrame(value) {
  const payload = Buffer.from(value, "utf8");
  if (payload.length > 125) {
    throw new Error("The realtime stub only emits bounded control frames");
  }
  const frame = Buffer.allocUnsafe(payload.length + 2);
  frame[0] = 0x81;
  frame[1] = payload.length;
  payload.copy(frame, 2);
  return frame;
}

function shutdown() {
  for (const socket of sockets) socket.destroy();
  server.close(() => process.exit(0));
}

process.once("SIGINT", shutdown);
process.once("SIGTERM", shutdown);
server.listen(port, host);
