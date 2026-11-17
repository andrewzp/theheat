"""Owned dashboard listener reservation for invented local HTTP journeys."""

from contextlib import contextmanager
import socket
from urllib.parse import urlsplit


@contextmanager
def reserve_dashboard_listener(origin=None):
    port = 0
    if origin is not None:
        parsed = urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("explicit_dashboard_loopback_origin_required")
        port = parsed.port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        # Match Node's restart behavior, but establish the exclusive listening
        # owner before exposing the port. Never enable SO_REUSEPORT.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen()
        yield listener, f"http://127.0.0.1:{listener.getsockname()[1]}"


def listener_fd(listener, origin):
    if not isinstance(listener, socket.socket) or listener.fileno() < 3:
        raise ValueError("owned_dashboard_listener_required")
    host, port = listener.getsockname()
    if host != "127.0.0.1" or origin != f"http://127.0.0.1:{port}":
        raise ValueError("dashboard_listener_origin_mismatch")
    return listener.fileno()
