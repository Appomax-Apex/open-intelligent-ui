"""Local measurement proxies for the 1A run. Never logs headers, keys or bodies.

- 127.0.0.1:8899  reverse proxy to https://api.anthropic.com; logs only model + usage per response.
- 127.0.0.1:8898  HTTP CONNECT proxy; logs only destination host:port, times and byte counts.
"""
import asyncio
import json
import sys
import time

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

LOG = sys.argv[1]
UPSTREAM = "https://api.anthropic.com"
HOP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding", "keep-alive"}
client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30), trust_env=False)


def log(rec):
    rec["t"] = round(time.time(), 3)
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


async def anthropic(request):
    body = await request.body()
    model = None
    try:
        model = json.loads(body).get("model")
    except Exception:
        pass
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["accept-encoding"] = "identity"
    t0 = time.time()
    req = client.build_request(request.method, UPSTREAM + request.url.path,
                               params=request.query_params, headers=headers, content=body)
    up = await client.send(req, stream=True)
    out_headers = {k: v for k, v in up.headers.items() if k.lower() not in HOP | {"content-encoding"}}
    usage = {}
    state = {"first": None}

    async def gen():
        buf = b""
        whole = []
        try:
            async for chunk in up.aiter_bytes():
                if state["first"] is None:
                    state["first"] = time.time()
                yield chunk
                if "text/event-stream" in up.headers.get("content-type", ""):
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.startswith(b"data:"):
                            try:
                                ev = json.loads(line[5:].strip())
                            except Exception:
                                continue
                            if ev.get("type") == "message_start":
                                usage.update(ev.get("message", {}).get("usage", {}) or {})
                            elif ev.get("type") == "message_delta" and ev.get("usage"):
                                usage.update({k: v for k, v in ev["usage"].items() if v is not None})
                else:
                    whole.append(chunk)
        finally:
            await up.aclose()
            if whole:
                try:
                    usage.update(json.loads(b"".join(whole)).get("usage", {}) or {})
                except Exception:
                    pass
            log({"kind": "anthropic", "path": request.url.path, "status": up.status_code, "model": model,
                 "t0": round(t0, 3), "first_byte_s": round((state["first"] or time.time()) - t0, 3),
                 "dur_s": round(time.time() - t0, 3), "usage": usage})

    return StreamingResponse(gen(), status_code=up.status_code, headers=out_headers)


app = Starlette(routes=[Route("/{path:path}", anthropic, methods=["GET", "POST"])])


async def pipe(r, w, counter, key):
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            counter[key] += len(data)
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def connect_handler(reader, writer):
    t0 = time.time()
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except Exception:
        writer.close()
        return
    first = head.split(b"\r\n", 1)[0].decode(errors="replace")
    parts = first.split(" ")
    if len(parts) < 2 or parts[0] != "CONNECT":
        log({"kind": "proxy_non_connect", "method": parts[0], "host": parts[1].split("/")[2] if "://" in parts[1] else parts[1]})
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\ncontent-length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        return
    host, _, port = parts[1].rpartition(":")
    counter = {"up": 0, "down": 0}
    try:
        ur, uw = await asyncio.open_connection(host, int(port))
    except Exception as exc:
        log({"kind": "connect", "host": host, "port": port, "error": type(exc).__name__})
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        writer.close()
        return
    writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(pipe(reader, uw, counter, "up"), pipe(ur, writer, counter, "down"))
    log({"kind": "connect", "host": host, "port": port, "t0": round(t0, 3),
         "dur_s": round(time.time() - t0, 3), "bytes_up": counter["up"], "bytes_down": counter["down"]})


async def main():
    srv = await asyncio.start_server(connect_handler, "127.0.0.1", 8898)
    config = uvicorn.Config(app, host="127.0.0.1", port=8899, log_level="warning")
    async with srv:
        await asyncio.gather(srv.serve_forever(), uvicorn.Server(config).serve())


asyncio.run(main())
