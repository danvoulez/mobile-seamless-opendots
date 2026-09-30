"""Facts about the computer Open Dots runs on, for linking other devices."""

import ipaddress
import platform
import socket
import subprocess
from functools import lru_cache
from typing import Dict, List, Optional

from app.config import settings


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _scutil(key: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["scutil", "--get", key], capture_output=True, text=True, timeout=2, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def is_mac() -> bool:
    return platform.system() == "Darwin"


@lru_cache(maxsize=1)
def computer_name() -> str:
    """The name people know this computer by, e.g. "Dana's MacBook Pro"."""
    return (is_mac() and _scutil("ComputerName")) or socket.gethostname().split(".")[0] or "Computer"


def device_label() -> str:
    """Short label for messages sent from this computer's own browser."""
    return "Mac" if is_mac() else "Computer"


@lru_cache(maxsize=1)
def mdns_hostname() -> Optional[str]:
    """The Bonjour name (``name.local``) that stays valid when the IP changes."""
    if not is_mac():
        return None
    name = _scutil("LocalHostName")
    return f"{name}.local" if name else None


def _classify(address: str) -> Optional[str]:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if ip.version != 4 or ip.is_loopback or ip.is_link_local:
        return None
    if ip in ipaddress.ip_network("100.64.0.0/10"):
        return "Tailscale"
    if ip.is_private:
        return "Local network"
    return None


def lan_addresses() -> List[Dict[str, str]]:
    found: Dict[str, str] = {}
    # Connecting a UDP socket sends nothing; it reveals the outbound interface.
    for probe in ("192.0.2.1", "100.100.100.100"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((probe, 9))
                address = sock.getsockname()[0]
        except OSError:
            continue
        if (kind := _classify(address)) and address not in found:
            found[address] = kind
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if (kind := _classify(address)) and address not in found:
                found[address] = kind
    except OSError:
        pass
    return [{"address": address, "kind": kind} for address, kind in found.items()]


def listening_beyond_loopback() -> bool:
    return settings.HOST not in LOOPBACK_HOSTS


def base_urls() -> List[Dict[str, str]]:
    """Addresses a phone can use to reach this server, best first."""
    if settings.PUBLIC_URL:
        return [{"url": settings.PUBLIC_URL, "kind": "Configured address"}]
    urls = []
    if host := mdns_hostname():
        urls.append({"url": f"http://{host}:{settings.PORT}", "kind": "Bonjour name"})
    for entry in lan_addresses():
        urls.append({"url": f"http://{entry['address']}:{settings.PORT}", "kind": entry["kind"]})
    return urls
