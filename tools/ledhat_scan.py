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
import sys
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
    BASE_UUID.format("fee9"): "Quintic/NXP QPP serial service (QN902x board)",
    BASE_UUID.format("ae00"): "QN (Quintic) vendor serial service",
    "6e400001-b5a3-f393-e0a9-e50e24dcca9e": "Nordic UART Service (NUS)",
}

# Services that positively rule a device OUT. A neighbour's earbuds can carry a
# vendor serial service too, so it is worth naming the ones that settle it.
DISQUALIFYING_SERVICES = {
    BASE_UUID.format("fe2c"): "Google Fast Pair - an audio accessory, not a display",
    BASE_UUID.format("fd6f"): "Exposure Notification - a phone, not a display",
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

    for uuid, description in DISQUALIFYING_SERVICES.items():
        if uuid in lowered:
            return None, [f"RULED OUT: {description}"]

    hints = [
        description
        for uuid, description in GENERIC_SERIAL_SERVICES.items()
        if uuid in lowered
    ]
    return None, hints


def looks_interesting(hit: Hit) -> bool:
    """Filter out the ambient noise of headphones, watches and beacons."""
    if any(h.startswith("RULED OUT") for h in hit.hints):
        return False
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


async def prompt(message: str) -> None:
    """Block for Enter without stalling the event loop."""
    await asyncio.get_running_loop().run_in_executor(None, input, message)


async def run_ab(seconds: float) -> None:
    """Scan twice around a power cycle; whatever vanishes is your device.

    Signal strength alone cannot tell your hat from a neighbour's earbuds, and
    a vendor serial service is not proof either. Turning the thing off is.
    """
    print("Make sure the hat is powered ON and unplugged from USB.")
    await prompt("Press Enter to scan... ")
    before = {h.address: h for h in await scan(seconds)}
    print(f"  saw {len(before)} device(s)\n")

    print("Now power the hat OFF (or walk it out of range).")
    await prompt("Press Enter to scan again... ")
    after = {h.address: h for h in await scan(seconds)}
    print(f"  saw {len(after)} device(s)\n")

    vanished = [before[a] for a in before.keys() - after.keys()]
    if not vanished:
        print("Nothing disappeared. Either the hat never advertised in the first")
        print("scan, or it is still powered. Check it and run --ab again.")
        return

    # A weak device can drop out of any single scan by chance, so rank by signal:
    # the hat was a metre from the laptop, a flaky neighbour's device was not.
    vanished.sort(key=lambda h: -h.rssi)
    print(f"{len(vanished)} device(s) present before and gone after:\n")
    report(vanished)
    if len(vanished) > 1:
        print("More than one dropped out. The strongest signal is the best bet;")
        print("re-run --ab to confirm - genuine drop-outs repeat, chance ones do not.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10.0, help="scan duration")
    parser.add_argument("--all", action="store_true", help="show every BLE device")
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    parser.add_argument("--ab", action="store_true",
                        help="scan before and after powering the hat off, and "
                             "report what disappeared")
    args = parser.parse_args()

    if args.ab:
        await run_ab(args.seconds)
        return

    hits = await scan(args.seconds)
    seen = len(hits)
    if not args.all:
        hits = [h for h in hits if looks_interesting(h)]

    if args.json:
        print(json.dumps([vars(h) for h in hits], indent=2))
        return

    if hits:
        report(hits)
        if seen > len(hits):
            print(f"({seen - len(hits)} other device(s) hidden; --all shows them.)")
        print("Next: python3 tools/ledhat_gatt.py <address>")
        return

    # "The radio saw nothing" and "nothing looked like an LED display" have
    # completely different causes, so never report them with the same message.
    if seen:
        print(f"Saw {seen} BLE device(s), but none looked like an LED display.")
        print()
        print("Re-run with --all to see them: the hat may advertise under an opaque")
        print("name (a bare MAC, 'BT-05', a model number) that the filter misses.")
        print("If it is not in the --all list either, the hat is not advertising --")
        print("power cycle it, unplug it from USB, or hold its button for pairing")
        print("mode. Some boards only advertise for ~60s after power-on.")
        return

    print("Saw no BLE devices at all -- that is a host problem, not the hat.")
    if sys.platform == "darwin":
        print()
        print("On macOS this is almost always Bluetooth permission: System Settings")
        print("> Privacy & Security > Bluetooth, and enable your terminal app. If it")
        print("is already enabled there, quit and reopen the terminal -- the grant")
        print("only applies to a newly launched process.")
    else:
        print("Check the adapter is up (bluetoothctl list) and not blocked")
        print("(rfkill list bluetooth).")


if __name__ == "__main__":
    asyncio.run(main())
