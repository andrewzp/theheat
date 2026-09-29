"""SDK-declared transport family, not a guessed version or installed-module preference."""

from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import pytest

from src.two_bot import provider_http


def test_real_public_sdk_client_matches_selected_family_without_network():
    family = provider_http.anthropic_httpx()
    assert family.__name__ in {"httpx", "httpx2"}
    assert issubclass(anthropic.DefaultHttpxClient, family.Client)


@pytest.mark.parametrize("name", ["httpx", "httpx2"])
def test_presence_of_both_libraries_does_not_override_sdk_client(monkeypatch, name):
    class OldClient:
        pass

    class NewClient:
        pass

    modules = {"httpx": SimpleNamespace(Client=OldClient),
               "httpx2": SimpleNamespace(Client=NewClient)}
    monkeypatch.setattr(provider_http, "import_module", modules.__getitem__)
    monkeypatch.setattr(anthropic, "DefaultHttpxClient", modules[name].Client)
    assert provider_http.anthropic_httpx() is modules[name]


def test_missing_old_module_does_not_hide_new_sdk_family(monkeypatch):
    class NewClient:
        pass

    module = SimpleNamespace(Client=NewClient)

    def imports(name):
        if name == "httpx":
            raise ImportError("not installed")
        return module

    monkeypatch.setattr(provider_http, "import_module", imports)
    monkeypatch.setattr(anthropic, "DefaultHttpxClient", NewClient)
    assert provider_http.anthropic_httpx() is module


@pytest.mark.parametrize("client", [object, lambda: None])
def test_unknown_family_is_not_silently_replaced(monkeypatch, client):
    monkeypatch.setattr(anthropic, "DefaultHttpxClient", client)
    with pytest.raises(RuntimeError, match="unsupported_anthropic_http_client_family"):
        provider_http.anthropic_httpx()
