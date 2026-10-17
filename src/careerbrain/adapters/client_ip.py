from __future__ import annotations

from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

Network = IPv4Network | IPv6Network
UNKNOWN_PEER = "unknown"


def parse_networks(values: Sequence[str]) -> list[Network]:
    return [
        ip_network(value.strip(), strict=False) for value in values if value.strip()
    ]


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted: Sequence[Network],
) -> str:
    peer_ip = peer or UNKNOWN_PEER
    if not forwarded_for or not _is_trusted(peer_ip, trusted):
        return peer_ip
    for hop in reversed([part.strip() for part in forwarded_for.split(",")]):
        if not _is_ip(hop):
            return peer_ip
        if not _is_trusted(hop, trusted):
            return hop
    return peer_ip


def _is_ip(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def _is_trusted(value: str, trusted: Sequence[Network]) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in trusted)
