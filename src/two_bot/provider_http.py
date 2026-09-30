"""Match the Anthropic SDK's public HTTP client family, without provider I/O."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


def anthropic_httpx() -> ModuleType:
    """Support verified HTTPX client families; unknown SDK transports refuse.

    Older supported SDKs used httpx; current pinned Anthropic uses httpx2.
    Inspect the public default client, not a guessed version cutoff or private
    SDK member. Merely having httpx2 installed must not change an older SDK.
    """
    from anthropic import DefaultHttpxClient

    if not isinstance(DefaultHttpxClient, type):
        raise RuntimeError("unsupported_anthropic_http_client_family")
    for name in ("httpx", "httpx2"):
        try:
            module = import_module(name)
        except ImportError:
            continue
        if issubclass(DefaultHttpxClient, module.Client):
            return module
    raise RuntimeError("unsupported_anthropic_http_client_family")
