"""The conftest guard really blocks connections (it must not pass vacuously)."""

import socket
import urllib.request

import pytest

from conftest import NetworkBlocked


def test_socket_connect_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(NetworkBlocked):
            s.connect(("127.0.0.1", 9))


def test_create_connection_is_blocked():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443), timeout=1)


def test_http_client_is_blocked():
    with pytest.raises((NetworkBlocked, urllib.error.URLError)) as exc:
        urllib.request.urlopen("http://127.0.0.1:9/", timeout=1)
    # urllib may wrap the error; either way the cause is the guard.
    err = exc.value
    assert isinstance(err, NetworkBlocked) or isinstance(err.reason, NetworkBlocked)
