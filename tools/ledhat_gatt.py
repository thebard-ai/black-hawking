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


async def subscribe(client: BleakClient, uuids: list[str]) -> list[str]:
    """Subscribe to every notify characteristic; return the ones that took."""
    def on_notify(sender, data: bytearray) -> None:
        print(f"[{stamp()}] {sender.uuid}  {render(bytes(data))}")

    started: list[str] = []
    for uuid in uuids:
        try:
            await client.start_notify(uuid, on_notify)
            started.append(uuid)
        except Exception as exc:  # noqa: BLE001
            print(f"could not subscribe to {uuid}: {exc}")
    return started


async def unsubscribe(client: BleakClient, uuids: list[str]) -> None:
    for uuid in uuids:
        with contextlib.suppress(Exception):
            await client.stop_notify(uuid)


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
    args = parser.parse_args()

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
