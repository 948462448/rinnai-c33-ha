#!/usr/bin/env python3
"""Tiny TCP capture server for Rinnai C33/HF-LPB100 boiler traffic."""

from __future__ import annotations

import argparse
import datetime as dt
import http.server
import pathlib
import socket
import threading
from urllib.parse import parse_qs, urlparse

LOG_LOCK = threading.Lock()
CLIENT_LOCK = threading.Lock()
CURRENT_CLIENT: socket.socket | None = None
CURRENT_LOG_PATH: pathlib.Path | None = None


def printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data)


def write_log(log_path: pathlib.Path, line: str) -> None:
    with LOG_LOCK:
        print(line, end="", flush=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(line)
            log.flush()


def record_packet(log_path: pathlib.Path, peer: str, direction: str, data: bytes) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    hex_data = data.hex(" ")
    text_data = printable(data)
    line = f"[{now}] {direction} {peer} len={len(data)} hex={hex_data} ascii={text_data}\n"
    write_log(log_path, line)


def command_frame(field_id: int, value: int) -> bytes:
    return bytes([0xFA, 0xD4, 0x9F, 0x37, 0xFF, 0xFF, 0x04, 0x00, field_id, 0x0E, 0x01, value])


def set_current_client(conn: socket.socket | None, log_path: pathlib.Path | None) -> None:
    global CURRENT_CLIENT, CURRENT_LOG_PATH
    with CLIENT_LOCK:
        CURRENT_CLIENT = conn
        CURRENT_LOG_PATH = log_path


def send_control_frame(field_id: int, value: int) -> bytes:
    with CLIENT_LOCK:
        conn = CURRENT_CLIENT
        log_path = CURRENT_LOG_PATH
    if conn is None or log_path is None:
        raise RuntimeError("no connected Rinnai remote")

    frame = command_frame(field_id, value)
    conn.sendall(frame)
    record_packet(log_path, "local-control", "control->remote", frame)
    return frame


class ControlHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/dhw":
                field_id = 0x14
                value = int(query["temperature"][0])
            elif parsed.path == "/heating":
                field_id = 0x18
                value = 1 if query.get("enabled", ["0"])[0] in ("1", "true", "on") else 0
            elif parsed.path == "/fast":
                field_id = 0x13
                value = 1 if query.get("enabled", ["0"])[0] in ("1", "true", "on") else 0
            elif parsed.path == "/command":
                field_id = int(query["field"][0], 0)
                value = int(query["value"][0], 0)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"unknown endpoint\n")
                return

            frame = send_control_frame(field_id, value)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"sent {frame.hex(' ')}\n".encode())
        except Exception as err:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(f"error: {err}\n".encode())

    def log_message(self, fmt: str, *args: object) -> None:
        return


def start_control_server(host: str, port: int) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer((host, port), ControlHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Control API listening on http://{host}:{port}")
    return server


def handle_stream(conn: socket.socket, peer: str, log_path: pathlib.Path) -> None:
    with conn:
        conn.settimeout(600)
        start = dt.datetime.now().isoformat(timespec="seconds")
        write_log(log_path, f"\n[{start}] CONNECT {peer}\n")

        while True:
            data = conn.recv(4096)
            if not data:
                end = dt.datetime.now().isoformat(timespec="seconds")
                write_log(log_path, f"[{end}] DISCONNECT {peer}\n")
                return
            record_packet(log_path, peer, "RX", data)


def relay(
    src: socket.socket,
    dst: socket.socket,
    peer: str,
    direction: str,
    log_path: pathlib.Path,
) -> None:
    try:
        while True:
            data = src.recv(4096)
            if not data:
                return
            record_packet(log_path, peer, direction, data)
            dst.sendall(data)
    except OSError as err:
        now = dt.datetime.now().isoformat(timespec="seconds")
        write_log(log_path, f"[{now}] {direction} {peer} error={err}\n")
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle_proxy(
    conn: socket.socket,
    addr: tuple[str, int],
    upstream_host: str,
    upstream_port: int,
    log_path: pathlib.Path,
) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    upstream_name = f"{upstream_host}:{upstream_port}"
    start = dt.datetime.now().isoformat(timespec="seconds")
    write_log(log_path, f"\n[{start}] CONNECT {peer} upstream={upstream_name}\n")
    try:
        with conn, socket.create_connection((upstream_host, upstream_port), timeout=10) as upstream:
            set_current_client(conn, log_path)
            conn.settimeout(600)
            upstream.settimeout(600)
            write_log(log_path, f"[{dt.datetime.now().isoformat(timespec='seconds')}] UPSTREAM_CONNECTED {peer} upstream={upstream_name}\n")
            up = threading.Thread(
                target=relay,
                args=(conn, upstream, peer, "remote->cloud", log_path),
                daemon=True,
            )
            down = threading.Thread(
                target=relay,
                args=(upstream, conn, peer, "cloud->remote", log_path),
                daemon=True,
            )
            up.start()
            down.start()
            up.join()
            down.join()
    except OSError as err:
        now = dt.datetime.now().isoformat(timespec="seconds")
        write_log(log_path, f"[{now}] PROXY_ERROR {peer} upstream={upstream_name} error={err}\n")
    finally:
        with CLIENT_LOCK:
            if CURRENT_CLIENT is conn:
                set_current_client(None, None)
        end = dt.datetime.now().isoformat(timespec="seconds")
        write_log(log_path, f"[{end}] DISCONNECT {peer}\n")


def handle_client(
    conn: socket.socket,
    addr: tuple[str, int],
    log_path: pathlib.Path,
    upstream_host: str | None,
    upstream_port: int,
) -> None:
    if upstream_host:
        handle_proxy(conn, addr, upstream_host, upstream_port, log_path)
        return

    peer = f"{addr[0]}:{addr[1]}"
    handle_stream(conn, peer, log_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=6969)
    parser.add_argument("--connect", help="Connect to a remote TCP server instead of listening")
    parser.add_argument("--upstream-host", help="Proxy accepted TCP clients to this host while logging traffic")
    parser.add_argument("--upstream-port", type=int, default=6969)
    parser.add_argument("--control-host", default="")
    parser.add_argument("--control-port", type=int, default=6970)
    parser.add_argument(
        "--log",
        default=f"captures/rinnai_c33_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    )
    args = parser.parse_args()

    log_path = pathlib.Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if args.connect:
        sock = socket.create_connection((args.connect, args.port), timeout=10)
        handle_stream(sock, f"{args.connect}:{args.port}", log_path)
        return

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(5)
    control_server = None
    if args.control_host:
        control_server = start_control_server(args.control_host, args.control_port)

    print(f"Listening on {args.host}:{args.port}")
    print(f"Writing capture log to {log_path}")

    try:
        while True:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr, log_path, args.upstream_host, args.upstream_port),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.close()
        if control_server is not None:
            control_server.shutdown()


if __name__ == "__main__":
    main()
