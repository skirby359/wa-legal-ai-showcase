"""Test-suite guard: no test may open a network connection.

The demo needs no network, so any connection attempt is a bug. Production has
the same kind of guard aimed at paid LLM APIs: it wraps the HTTP client the
vendor SDKs use, blocks requests to the Anthropic/OpenAI hosts, and fails the
test that tried. It was added after a test run was found calling a paid API
because a key in the environment let the code auto-select a hosted model.
Removing the key did not help, because the app reloaded it from its own
config. A guard in the test harness does not depend on the environment.
"""

from __future__ import annotations

import socket

import pytest


class NetworkBlocked(RuntimeError):
    """Raised when a test tries to open a network connection."""


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection


def _blocked(*_args, **_kwargs):
    raise NetworkBlocked("network access is blocked in tests (see tests/conftest.py)")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield
