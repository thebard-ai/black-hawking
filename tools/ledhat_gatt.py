#!/usr/bin/env python3
"""Connect to a BLE LED display, dump its GATT tree, and optionally poke it.

    # See every service, characteristic and property the device exposes.
    python3 tools/ledhat_gatt.py AA:BB:CC:DD:EE:FF

    # Listen on every notify characteristic for 30s while you press the hat's button.
    python3 tools/ledhat_gatt.py AA:BB:CC:DD:EE:FF --listen 30

    # Replay one frame captured from the vendor app and watch what comes back.
    python3 tools/ledhat_gatt.py AA:BB:CC:DD:EE:FF --write 0000fff1-... --hex 01020304
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import datetime

from bleak import BleakClient

# Characteristics that are safe to read without side effects.
SAFE_TO_READ = {
    "00002a00",  # Device Name
    "00002a24",  # Model Number
    "00002a25",  # Serial Number
    "00002a26",  # Firmware Revision
    "00002a27",  # Hardware Revision
    "00002a28",  # Software Revision
    "00002a29",  # Manufacturer Name
    "00002a19",  # Battery Level
}


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def render(data: bytes) -> str:
    """Hex plus a printable-ASCII gutter, the way a packet dump wants to be read."""
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{data.hex(' ')}  |{printable}|"


async def dump(client: BleakClient) -> list[str]:
    """Print the GATT tree; return the UUIDs that support notify/indicate."""
    notifiable: list[str] = []
    for service in client.services:
        print(f"\nservice {service.uuid}  {service.description}")
        for char in service.characteristics:
            props = ",".join(char.properties)
            print(f"  char  {char.uuid}  [{props}]  {char.description}")

            if {"notify", "indicate"} & set(char.properties):
                notifiable.append(char.uuid)

            if "read" in char.properties and char.uuid[:8] in SAFE_TO_READ:
                try:
                    value = await client.read_gatt_char(char.uuid)
                    print(f"        read -> {render(value)}")
                except Exception as exc:  # noqa: BLE001 - report, never abort the dump
                    print(f"        read failed: {exc}")

            for descriptor in char.descriptors:
                print(f"        desc {descriptor.uuid}  {descriptor.description}")
    return notifiable


async def subscribe(client: BleakClient, uuids: list[str], handler=None) -> list[str]:
    """Subscribe to every notify characteristic; return the ones that took."""
    def on_notify(sender, data: bytearray) -> None:
        print(f"[{stamp()}] {sender.uuid}  {render(bytes(data))}")

    handler = handler or on_notify
    started: list[str] = []
    for uuid in uuids:
        try:
            await client.start_notify(uuid, handler)
            started.append(uuid)
        except Exception as exc:  # noqa: BLE001
            print(f"could not subscribe to {uuid}: {exc}")
    return started


async def unsubscribe(client: BleakClient, uuids: list[str]) -> None:
    for uuid in uuids:
        with contextlib.suppress(Exception):
            await client.stop_notify(uuid)


VERDICTS = {
    "inconsistent": (
        "inconsistent - did not greet on every connection.",
        ("Re-run with more rounds; an unreliable greeting classifies nothing.",),
    ),
    "stable": (
        "STABLE across every connection.",
        ("An identifier or status blob. Not a handshake; ignore it.",),
    ),
    "nonce": (
        "CHANGES every connection.",
        ("A challenge/nonce. Expect an auth handshake before the",
         "device accepts display commands."),
    ),
}


def classify_greeting(seen: list[bytes | None]) -> str:
    """Decide what a device's opening notification is, from one per connection."""
    if not seen or any(v is None for v in seen):
        return "inconsistent"
    return "stable" if len(set(seen)) == 1 else "nonce"


def notifiable_uuids(client: BleakClient) -> list[str]:
    return [
        char.uuid
        for service in client.services
        for char in service.characteristics
        if {"notify", "indicate"} & set(char.properties)
    ]


async def probe_greeting(address: str, rounds: int, timeout: float) -> None:
    """Connect several times over and compare the device's opening notification.

    A payload that changes every connection is a challenge/nonce, and commands
    will need a handshake first. One that never changes is an identifier or a
    status blob, and can be ignored. Telling those apart decides whether the
    protocol work starts with crypto or not, so it is worth the thirty seconds.
    """
    greetings: list[dict[str, bytes]] = []

    for round_number in range(1, rounds + 1):
        first: dict[str, bytes] = {}

        def capture(sender, data: bytearray) -> None:
            # Only the opening payload per characteristic; later traffic is noise.
            first.setdefault(sender.uuid, bytes(data))

        async with BleakClient(address, timeout=timeout) as client:
            started = await subscribe(client, notifiable_uuids(client), capture)
            await asyncio.sleep(2.0)
            await unsubscribe(client, started)

        print(f"connection {round_number}:")
        for uuid, payload in sorted(first.items()):
            print(f"  {uuid}  {render(payload)}")
        if not first:
            print("  (silence)")
        greetings.append(first)
        if round_number < rounds:
            await asyncio.sleep(1.0)

    every_uuid = sorted({u for g in greetings for u in g})
    if not every_uuid:
        print("\nThe device never spoke first. Nothing to classify.")
        return

    print()
    for uuid in every_uuid:
        verdict = classify_greeting([g.get(uuid) for g in greetings])
        print(f"{uuid}: {VERDICTS[verdict][0]}")
        for line in VERDICTS[verdict][1]:
            print(f"   {line}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="BLE MAC address (or UUID on macOS)")
    parser.add_argument("--listen", type=float, default=0.0,
                        help="seconds to log notifications after the dump")
    parser.add_argument("--write", metavar="UUID",
                        help="characteristic to write --hex to")
    parser.add_argument("--hex", help="payload as hex, e.g. 01020304 or '01 02 03 04'")
    parser.add_argument("--no-response", action="store_true",
                        help="use write-without-response")
    parser.add_argument("--timeout", type=float, default=20.0,
                        help="connection timeout")
    parser.add_argument("--probe", nargs="?", type=int, const=3, metavar="N",
                        help="connect N times (default 3) and report whether the "
                             "device's opening notification is a nonce or fixed")
    args = parser.parse_args()

    if args.probe:
        await probe_greeting(args.address, args.probe, args.timeout)
        return

    if bool(args.write) != bool(args.hex):
        parser.error("--write and --hex must be given together")

    async with BleakClient(args.address, timeout=args.timeout) as client:
        print(f"connected to {args.address}")
        notifiable = await dump(client)

        if not notifiable:
            print("\nNo notify/indicate characteristics: the device will not talk back.")

        # Subscribe before writing so we catch the reply to our own frame.
        started = await subscribe(client, notifiable)

        if args.write:
            payload = bytes.fromhex(args.hex.replace(" ", ""))
            print(f"\nwrite {args.write} <- {render(payload)}")
            await client.write_gatt_char(
                args.write, payload, response=not args.no_response
            )

        # A write with no --listen still gets a short window to catch the ack.
        window = args.listen or (2.0 if args.write else 0.0)
        if window and started:
            print(f"\nListening {window:g}s on {len(started)} characteristic(s). "
                  "Press the hat\'s buttons, change modes, let it idle.\n")
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(window)

        await unsubscribe(client, started)


if __name__ == "__main__":
    asyncio.run(main())
