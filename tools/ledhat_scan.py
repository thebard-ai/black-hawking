#!/usr/bin/env python3
"""Scan for BLE LED displays and fingerprint them against known protocol families.

Run this with the hat powered on, unplugged from USB, and the vendor app CLOSED
(the app holds an exclusive connection while it is running).

    python3 tools/ledhat_scan.py
    python3 tools/ledhat_scan.py --seconds 20 --all --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field

from bleak import BleakScanner


@dataclass(frozen=True)
class Family:
    """A known LED-display protocol family and how to recognise it over the air."""

    key: str
    label: str
    name_exact: tuple[str, ...] = ()
    name_prefix: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    driver: str = ""


# Short UUIDs are expanded to the 128-bit Bluetooth base UUID before comparing.
BASE_UUID = "0000{:s}-0000-1000-8000-00805f9b34fb"

FAMILIES: tuple[Family, ...] = (
    Family(
        key="coolledx",
        label="CoolLEDX (CoolLED1248 app)",
        name_exact=("CoolLEDX",),
        services=(BASE_UUID.format("fff0"),),
        driver="https://github.com/UpDryTwist/coolledx-driver  (pip install coolledx)",
    ),
    Family(
        key="coolledm",
        label="CoolLEDM (newer CoolLED1248 hardware)",
        name_exact=("CoolLEDM",),
        services=(BASE_UUID.format("fff0"),),
        driver="Partially supported by coolledx-driver; newer protocol, expect gaps.",
    ),
    Family(
        key="idotmatrix",
        label="iDotMatrix pixel display",
        name_prefix=("IDM-",),
        driver="https://github.com/derkalle4/python3-idotmatrix-library",
    ),
    Family(
        key="b1248",
        label="B1248-style LED name badge",
        name_exact=("LSLED", "B1248"),
        driver="https://cat-in-136.github.io/2020/07/b1248-led-name-badge-protocol-reverse-engineering.html",
    ),
)

# Vendor serial-over-BLE services. Not proof of a family, but a strong hint that
# the device takes framed command packets on a write characteristic.
GENERIC_SERIAL_SERVICES = {
    BASE_UUID.format("fff0"): "Generic 0xFFF0 vendor serial service",
    BASE_UUID.format("ffe0"): "Generic 0xFFE0 vendor serial service (HM-10 style)",
    "6e400001-b5a3-f393-e0a9-e50e24dcca9e": "Nordic UART Service (NUS)",
}


@dataclass
class Hit:
    """One scanned device plus whatever we could infer about it."""

    address: str
    name: str
    rssi: int
    services: list[str] = field(default_factory=list)
    manufacturer_data: dict[int, str] = field(default_factory=dict)
    family: str | None = None
    family_label: str | None = None
    driver: str | None = None
    hints: list[str] = field(default_factory=list)


def classify(name: str, services: list[str]) -> tuple[Family | None, list[str]]:
    """Match a device against the family table; return the family and soft hints."""
    lowered = {s.lower() for s in services}
    for fam in FAMILIES:
        if name in fam.name_exact or any(name.startswith(p) for p in fam.name_prefix):
            return fam, []
        if fam.services and lowered.issuperset(s.lower() for s in fam.services):
            return fam, ["matched on service UUID only; name did not match"]

    hints = [
        description
        for uuid, description in GENERIC_SERIAL_SERVICES.items()
        if uuid in lowered
    ]
    return None, hints


def looks_interesting(hit: Hit) -> bool:
    """Filter out the ambient noise of headphones, watches and beacons."""
    if hit.family or hit.hints:
        return True
    keywords = ("led", "matrix", "display", "screen", "badge", "sign", "magic")
    return any(k in hit.name.lower() for k in keywords)


async def scan(seconds: float) -> list[Hit]:
    discovered = await BleakScanner.discover(timeout=seconds, return_adv=True)
    hits: list[Hit] = []
    for device, adv in discovered.values():
        name = adv.local_name or device.name or ""
        services = list(adv.service_uuids or [])
        family, hints = classify(name, services)
        hits.append(
            Hit(
                address=device.address,
                name=name or "(no name)",
                rssi=adv.rssi,
                services=services,
                manufacturer_data={
                    company: payload.hex()
                    for company, payload in (adv.manufacturer_data or {}).items()
                },
                family=family.key if family else None,
                family_label=family.label if family else None,
                driver=family.driver if family else None,
                hints=hints,
            )
        )
    hits.sort(key=lambda h: (h.family is None, -h.rssi))
    return hits


def report(hits: list[Hit]) -> None:
    for hit in hits:
        marker = "**" if hit.family else "  "
        print(f"{marker} {hit.name}  [{hit.address}]  {hit.rssi} dBm")
        if hit.family_label:
            print(f"     family : {hit.family_label}")
            print(f"     driver : {hit.driver}")
        for hint in hit.hints:
            print(f"     hint   : {hint}")
        if hit.services:
            print(f"     svcs   : {', '.join(hit.services)}")
        for company, payload in hit.manufacturer_data.items():
            print(f"     mfr    : 0x{company:04x} {payload}")
        print()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10.0, help="scan duration")
    parser.add_argument("--all", action="store_true", help="show every BLE device")
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    args = parser.parse_args()

    hits = await scan(args.seconds)
    if not args.all:
        hits = [h for h in hits if looks_interesting(h)]

    if args.json:
        print(json.dumps([vars(h) for h in hits], indent=2))
        return

    if not hits:
        print("Nothing matched. Re-run with --all, and check the hat is powered on,")
        print("unplugged from USB, and not already connected to a phone.")
        return

    report(hits)
    print("Next: python3 tools/ledhat_gatt.py <address>")


if __name__ == "__main__":
    asyncio.run(main())
