#!/usr/bin/env python3
"""Start the LAN conversion service.

Colleagues open the printed URL in a browser on the same network. Nothing is
kept: uploads live in a per-request temporary directory and the workbook
streams back from memory.

The password comes from KMZ_PASSWORD, or is prompted for.
"""

from __future__ import annotations

import os
import socket
from getpass import getpass

from kmz_points.server import create_app

DEFAULT_PORT = 8000


def lan_address() -> str:
    """The address colleagues should use, not 127.0.0.1.

    Opening a UDP socket towards a routable address makes the OS choose the
    outbound interface, which is the one colleagues can reach. Nothing is
    actually sent.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _run_app(**kwargs) -> None:
    """Indirection so tests can start everything except the server itself."""
    create_app(kwargs.pop("password")).run(**kwargs)


def main() -> int:
    password = os.environ.get("KMZ_PASSWORD") or getpass("Password for colleagues: ")
    if not password.strip():
        print("A password is required.")
        return 1

    print()
    print(f"  Share this:  http://{lan_address()}:{DEFAULT_PORT}")
    print("  Stop with Ctrl-C")
    print()
    print("  The address can change if your laptop gets a new one from DHCP.")
    print()

    # threaded, so one large conversion does not block everyone else.
    _run_app(password=password, host="0.0.0.0", port=DEFAULT_PORT, threaded=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
