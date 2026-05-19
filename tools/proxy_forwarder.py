#!/usr/bin/env python3
"""Tiny local HTTP CONNECT proxy forwarder with upstream proxy authentication.

Usage:
  python3 tools/proxy_forwarder.py \
    --listen 127.0.0.1:18080 \
    --upstream proxy.example.com:8080:username:password

Chrome can then use --proxy-server=http://127.0.0.1:18080 without seeing an auth popup.
"""
import argparse
import base64
import select
import socket
import socketserver
import sys
import threading

BUFFER = 65536


class ForwardProxyHandler(socketserver.StreamRequestHandler):
    upstream_host = ""
    upstream_port = 0
    upstream_auth = ""

    def log_message(self, message):
        sys.stderr.write(message + "\n")

    def handle(self):
        first = self.rfile.readline(BUFFER)
        if not first:
            return
        try:
            request_line = first.decode("iso-8859-1").rstrip("\r\n")
            method, target, version = request_line.split(" ", 2)
        except ValueError:
            return

        headers = []
        while True:
            line = self.rfile.readline(BUFFER)
            if not line:
                return
            if line in (b"\r\n", b"\n"):
                break
            text = line.decode("iso-8859-1").rstrip("\r\n")
            if not text.lower().startswith("proxy-authorization:"):
                headers.append(text)

        try:
            upstream = socket.create_connection((self.upstream_host, self.upstream_port), timeout=20)
        except OSError as exc:
            self.wfile.write(f"HTTP/1.1 502 Bad Gateway\r\nContent-Length: {len(str(exc))}\r\n\r\n{exc}".encode())
            return

        with upstream:
            if method.upper() == "CONNECT":
                connect_req = (
                    f"CONNECT {target} {version}\r\n"
                    f"Host: {target}\r\n"
                    f"Proxy-Authorization: Basic {self.upstream_auth}\r\n"
                    f"Proxy-Connection: Keep-Alive\r\n"
                    f"\r\n"
                ).encode("iso-8859-1")
                upstream.sendall(connect_req)
                response = self._read_header(upstream)
                self.wfile.write(response)
                self.wfile.flush()
                if b" 200 " not in response.split(b"\r\n", 1)[0]:
                    return
                self._tunnel(self.connection, upstream)
                return

            # Forward absolute-form HTTP requests.
            outbound = [f"{method} {target} {version}", *headers]
            outbound.append(f"Proxy-Authorization: Basic {self.upstream_auth}")
            outbound.append("")
            outbound.append("")
            upstream.sendall("\r\n".join(outbound).encode("iso-8859-1"))
            self._tunnel(self.connection, upstream)

    def _read_header(self, sock):
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 1024 * 1024:
            chunk = sock.recv(BUFFER)
            if not chunk:
                break
            data += chunk
        return data

    def _tunnel(self, client, upstream):
        sockets = [client, upstream]
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 300)
            if errored or not readable:
                return
            for src in readable:
                try:
                    data = src.recv(BUFFER)
                except OSError:
                    return
                if not data:
                    return
                dst = upstream if src is client else client
                try:
                    dst.sendall(data)
                except OSError:
                    return


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def parse_host_port(value):
    host, port = value.rsplit(":", 1)
    return host, int(port)


def parse_upstream(value):
    parts = value.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("upstream must be host:port:user:pass")
    host, port, user, password = parts
    return host, int(port), user, password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1:18080")
    parser.add_argument("--upstream", required=True, type=parse_upstream)
    args = parser.parse_args()

    listen_host, listen_port = parse_host_port(args.listen)
    host, port, user, password = args.upstream
    ForwardProxyHandler.upstream_host = host
    ForwardProxyHandler.upstream_port = port
    ForwardProxyHandler.upstream_auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    with ThreadingTCPServer((listen_host, listen_port), ForwardProxyHandler) as server:
        print(f"listening http://{listen_host}:{listen_port} -> {host}:{port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
