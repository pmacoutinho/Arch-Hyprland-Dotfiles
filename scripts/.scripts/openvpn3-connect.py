#!/usr/bin/env python3
"""Start an OpenVPN 3 session with a username/password given on stdin.

Usage: openvpn3-connect.py CONFIG.ovpn LABEL [--check]

Reads two lines from stdin, the username then the password, and hands them to
the session's credential slots over D-Bus, so they never appear on a command
line or on disk. Prints "Connected to LABEL." or "Error: …" (used by the
HyprPanel VPN menu's notifications) and exits non-zero on failure.

With --check, stops before connecting: imports the config, starts a session,
lists the inputs it asks for, then removes the session. Nothing on stdin.
"""
import os
import sys
import time
from typing import NoReturn

import dbus
import openvpn3
from openvpn3 import (ClientAttentionGroup, ClientAttentionType, StatusMajor,
                      StatusMinor)

TIMEOUT = 45  # seconds to wait for the tunnel to come up


def fail(message, session=None) -> NoReturn:
    if session is not None:
        try:
            session.Disconnect()
        except dbus.exceptions.DBusException:
            pass
    print(f"Error: {message}")
    sys.exit(1)


def load_config(bus, path):
    """Import the .ovpn file (with its referenced cert/key files embedded)."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        fail(f"config not found: {path}")
    # Referenced files (ca, tls-auth, …) are relative to the config's folder.
    os.chdir(os.path.dirname(path))
    parser = openvpn3.ConfigParser(["openvpn3", "--config", path], "")
    manager = openvpn3.ConfigurationManager(bus)
    # Named after the file, like `openvpn3 session-start --config FILE` does,
    # so `openvpn3 session-manage --config FILE -D` still finds the session.
    return manager.Import(os.path.basename(path), parser.GenerateConfig(), True, False)


def ready(session, credentials, check=False):
    """Fill credential slots until the backend reports it's ready."""
    asked = []
    for _ in range(40):
        try:
            session.Ready()
            return asked
        except dbus.exceptions.DBusException as e:
            err = e.get_dbus_message() or str(e)
            if "Backend VPN process is not ready" in err:
                time.sleep(0.25)
                continue
            if "Missing user credentials" not in err:
                fail(err, session)
        slots = session.FetchUserInputSlots()
        for slot in slots:
            qtype, qgroup = slot.GetTypeGroup()
            name = slot.GetVariableName()
            asked.append(f"{qgroup.name}:{name}")
            if check:
                continue
            if (qtype == ClientAttentionType.CREDENTIALS
                    and qgroup == ClientAttentionGroup.USER_PASSWORD
                    and name in credentials):
                slot.ProvideInput(credentials[name])
            else:
                fail(f"the VPN asks for something this menu can't provide ({slot.GetLabel()})",
                     session)
        if check:
            return asked
    fail("timed out preparing the session", session)
    return asked


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    check = "--check" in sys.argv
    if len(args) != 2:
        print((__doc__ or "").strip().splitlines()[2])
        sys.exit(2)
    config_path, label = args

    credentials = {}
    if not check:
        lines = sys.stdin.read().split("\n")
        if len(lines) < 2 or not lines[0] or not lines[1]:
            fail("username and password are required")
        credentials = {"username": lines[0], "password": lines[1]}

    try:
        bus = dbus.SystemBus()
        config = load_config(bus, config_path)
        session = openvpn3.SessionManager(bus).NewTunnel(config)
    except dbus.exceptions.DBusException as e:
        fail(e.get_dbus_message() or str(e))

    asked = ready(session, credentials, check)
    credentials.clear()
    if check:
        print("Inputs requested: " + (", ".join(asked) or "none"))
        try:
            session.Disconnect()
        except dbus.exceptions.DBusException:
            pass
        return 0

    session.Connect()
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        status = session.GetStatus()
        if status["major"] == StatusMajor.CONNECTION:
            minor = status["minor"]
            if minor == StatusMinor.CONN_CONNECTED:
                print(f"Connected to {label}.")
                return 0
            if minor == StatusMinor.CONN_AUTH_FAILED:
                fail("wrong username or password", session)
            if minor in (StatusMinor.CONN_FAILED, StatusMinor.CONN_DISCONNECTED,
                         StatusMinor.CONN_DONE):
                fail(status["message"] or "connection failed", session)
        time.sleep(0.5)
    fail("timed out connecting", session)


if __name__ == "__main__":
    sys.exit(main())
