"""Launcher tests. The server itself is never started."""

import ipaddress

import pytest

import serve


class TestLanAddress:
    def test_it_reports_the_outbound_interface_address(self, monkeypatch):
        # The address is faked, because asserting only "is valid IPv4" would
        # also pass when the fallback fired -- 127.0.0.1 is a valid address,
        # and it is exactly the value that means this function failed.
        class Probe:
            def connect(self, _address):
                pass

            def getsockname(self):
                return ("192.168.1.42", 54321)

            def close(self):
                pass

        monkeypatch.setattr(serve.socket, "socket", lambda *a, **k: Probe())
        assert serve.lan_address() == "192.168.1.42"

    def test_the_real_call_still_returns_a_parseable_address(self):
        # No claim about which address: a runner with no route legitimately
        # gets the loopback fallback.
        ipaddress.IPv4Address(serve.lan_address())

    def test_it_falls_back_when_there_is_no_route(self, monkeypatch):
        class DeadSocket:
            def connect(self, _address):
                raise OSError("no route to host")

            def getsockname(self):  # pragma: no cover - never reached
                raise AssertionError("should not be asked")

            def close(self):
                pass

        monkeypatch.setattr(serve.socket, "socket", lambda *a, **k: DeadSocket())
        assert serve.lan_address() == "127.0.0.1"


class TestMain:
    def test_an_empty_password_stops_before_starting(self, monkeypatch, capsys):
        monkeypatch.setenv("KMZ_PASSWORD", "   ")
        assert serve.main() == 1
        assert "password" in capsys.readouterr().out.lower()

    def test_the_shared_url_is_printed(self, monkeypatch, capsys):
        monkeypatch.setenv("KMZ_PASSWORD", "hunter2")
        started = {}

        def fake_run(**kwargs):
            started.update(kwargs)

        monkeypatch.setattr(serve, "_run_app", fake_run)
        assert serve.main() == 0

        printed = capsys.readouterr().out
        assert f":{serve.DEFAULT_PORT}" in printed
        assert started["host"] == "0.0.0.0"
        assert started["threaded"] is True
