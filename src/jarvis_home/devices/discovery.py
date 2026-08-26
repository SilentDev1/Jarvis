"""LAN discovery for the terminal, without multicast.

The device previously found Jarvis by resolving a `.local` name over mDNS.
That works until the host moves between wired and wireless, at which point
multicast stops crossing the segments and the terminal sits on Wi-Fi, pingable,
unable to find Jarvis, needing a physical power cycle. That happened in
practice.

Broadcast is forwarded as ordinary link-layer traffic within a subnet, so it
survives that. The device broadcasts a fixed probe and the gateway answers with
its address; the device then caches it and does not need discovery again unless
the address changes.

The responder returns only the gateway's address and port. It performs no
authentication because it grants nothing: reaching the device WebSocket still
requires the device credential.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket

DISCOVERY_PORT = 8768
PROBE = b"JARVIS-DISCOVER-V1"
MAX_DATAGRAM = 64

logger = logging.getLogger("jarvis_home.discovery")


def local_address_for(peer: str) -> str:
    """Address this host presents on the route toward `peer`.

    Asking the routing table beats guessing an interface: it stays correct when
    the host moves between wired and wireless, which is exactly the failure
    this module exists to survive.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((peer, 9))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


class DiscoveryResponder(asyncio.DatagramProtocol):
    def __init__(self, port: int):
        self.port = port
        self.transport: asyncio.DatagramTransport | None = None
        self.answered = 0

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        # Ignore anything that is not the exact probe; this socket is open to
        # the LAN and should not try to interpret arbitrary traffic.
        if len(data) > MAX_DATAGRAM or data.strip() != PROBE:
            return
        reply = json.dumps({
            "service": "jarvis-device-gateway",
            "host": local_address_for(addr[0]),
            "port": self.port,
        }).encode()
        if self.transport is not None:
            self.transport.sendto(reply, addr)
            self.answered += 1
            logger.info("discovery answered for %s", addr[0])


async def start_discovery_responder(port: int) -> asyncio.DatagramTransport | None:
    """Best effort: discovery is a convenience, never a prerequisite."""
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: DiscoveryResponder(port),
            local_addr=("0.0.0.0", DISCOVERY_PORT),
            allow_broadcast=True,
        )
    except OSError as error:
        logger.warning("discovery responder unavailable: %s", error)
        return None
    logger.info("discovery responder listening on udp/%d", DISCOVERY_PORT)
    return transport


@contextlib.asynccontextmanager
async def discovery_responder(port: int):
    transport = await start_discovery_responder(port)
    try:
        yield transport
    finally:
        if transport is not None:
            transport.close()
