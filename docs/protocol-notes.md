# LED display hat — protocol notes

## Known families

Nearly every cheap BLE LED hat/badge/strip on the market is one of a small number of
OEM boards. Identify which one you have and you may not have to reverse anything.

| Family | Advertised name | GATT | Status |
|---|---|---|---|
| CoolLEDX (`CoolLED1248` app) | `CoolLEDX` | service `0xFFF0`, char `0000fff1-…` | Fully reverse engineered — [coolledx-driver](https://github.com/UpDryTwist/coolledx-driver), `pip install coolledx` |
| CoolLEDM (newer revision) | `CoolLEDM` | service `0xFFF0` | Partly supported; protocol differs from CoolLEDX |
| iDotMatrix pixel panels | `IDM-*` | vendor serial | Fully reverse engineered — [python3-idotmatrix-library](https://github.com/derkalle4/python3-idotmatrix-library) |
| B1248 / LSLED name badges | `LSLED`, `B1248` | vendor serial | [Documented protocol writeup](https://cat-in-136.github.io/2020/07/b1248-led-name-badge-protocol-reverse-engineering.html) |
| Magic Display (`com.tirohk.magicdisplay`, Tianlang / Shenzhen) | varies | vendor serial | No public driver found — this is the one that needs work |
| Quintic/NXP QN902x on QPPS | varies | service `0xFEE9`, chars `d44bc439-…-9254161296xx`; often `0xAE00` too | Transport is [documented](https://www.nxp.com/docs/en/application-note/AN11846.pdf), but it is a generic pipe — the frames inside it are still per-vendor |

The QR code on `api.e-toys.cn/page/app/64` is a vendor landing page that hands you an
APK plus an App Store link. The vendor site tells you nothing about the protocol; the
device's own BLE advertisement tells you everything you need to start.

See [`device-log.md`](device-log.md) for what the hardware in hand actually turned
out to be.

## Step 0 — prove which device is yours

A crowded 2.4GHz band means signal strength is a hint, not an answer, and a vendor
serial service is not proof either — a neighbour's earbuds can carry one. Scan either
side of a power cycle instead:

```sh
python3 tools/ledhat_scan.py --ab
```

It scans, waits while you switch the hat off, scans again, and reports what
disappeared. That is the only cheap test that actually identifies your device.

## Step 1 — identify over the air

```sh
pip install -r requirements.txt
python3 tools/ledhat_scan.py --seconds 15
```

The hat must be powered on, **unplugged from USB** (most of these boards disable the
radio while charging), and not already connected to a phone.

**On macOS**, grant your terminal Bluetooth access first:
System Settings → Privacy & Security → Bluetooth → enable Terminal / iTerm / your IDE.
Without it the scan runs happily and finds nothing at all.

Also on macOS: CoreBluetooth does not expose hardware MAC addresses. The "address"
you get back is a per-Mac UUID (`A1B2C3D4-…`). It is stable on that Mac and works
everywhere these tools want an address, but it will not match a MAC quoted in someone
else's writeup.

If the name matches a known family, stop reverse engineering and use the existing
driver. If it does not, continue.

## Step 2 — map the GATT tree

```sh
python3 tools/ledhat_gatt.py <ADDRESS> --listen 30
```

What you are looking for:

- One characteristic with `write` or `write-without-response` — the command sink.
- One characteristic with `notify` — the device's replies (acks, battery, firmware).
- Vendor serial services show up as `0xFFF0`, `0xFFE0` (HM-10 clone), or Nordic UART
  (`6e400001-b5a3-f393-e0a9-e50e24dcca9e`).

Almost all of these boards speak a framed byte protocol on a single write
characteristic, chunked to the ~20-byte BLE MTU.

## Step 3 — read the app without running it (Mac, no phone)

You do not need to install anything to learn the protocol. An APK is a zip file, and
these vendor apps are usually not obfuscated. Decompiling it is reading, not executing:

```sh
brew install jadx apktool
jadx -d app_src app.apk        # decompiled Java
apktool d app.apk -o app_res   # resources and smali, if you need them
```

Then grep the decompiled source for the UUIDs you found in step 2:

```sh
grep -rin "fff1\|fff0\|ffe1\|6e400001" app_src/
```

The class that references the write characteristic is the protocol encoder. Chinese
OEM apps of this class are usually thin wrappers over a `BluetoothManager` helper with
method names like `sendText`, `sendPic`, `setBright` — often in plain sight.

This is the highest-value step per unit of risk: you never run the vendor's code.

## Step 4 — capture live frames (pick a route)

Only needed if step 3 leaves the encoding ambiguous — usually the image/bitmap packing
rather than the simple commands.

| Route | Needs | Vendor code runs on | Notes |
|---|---|---|---|
| **nRF52840 dongle + Wireshark** | ~$10–25 dongle | nothing you own | Pure over-the-air sniffing, driven entirely from the Mac. Cleanest, but you wait for shipping. |
| **iPhone + PacketLogger** | an iPhone, Xcode Additional Tools | your iPhone | App Store build (reviewed, sandboxed) rather than a sideloaded APK — materially lower exposure than the Android route. Delete the app after capture. |
| **Burner Android + HCI snoop log** | a spare Android device | the burner | Most direct, but needs a device you're willing to dirty. |
| ~~Android emulator on the Mac~~ | — | — | **Does not work.** No mainstream emulator passes host Bluetooth through to the guest, so the emulated app cannot reach the physical hat. |

### Route: nRF52840 dongle

Flash the [nRF Sniffer for Bluetooth LE](https://www.nordicsemi.com/Products/Development-tools/nRF-Sniffer-for-Bluetooth-LE)
firmware, install its Wireshark extcap plugin, then sniff while a phone or the Mac
drives the hat. Filter on `btatt`. Start the capture *before* the connection is
established — the sniffer needs to see the connection event to follow the link.

### Route: iPhone + PacketLogger

1. Download **Additional Tools for Xcode** from developer.apple.com; PacketLogger is
   in the `Hardware` folder.
2. Connect the iPhone by cable, then **File → New iOS Trace**.
3. Drive the app: connect, set one pixel, set text, change brightness, change speed.
4. Export to BTSnoop and open in Wireshark, or read it in PacketLogger directly.

PacketLogger also traces the **Mac's own** Bluetooth stack, which is how you verify
the frames your Python sends in step 5.

### Route: burner Android

1. Developer options → **Enable Bluetooth HCI snoop log**.
2. Toggle Bluetooth off and on.
3. Drive the app as above.
4. Pull the log:
   ```sh
   adb bugreport bugreport.zip     # snoop log lives inside on modern Android
   # older devices: adb pull /sdcard/btsnoop_hci.log
   ```

### Whichever route you take

Change **one variable at a time** and write down what you did and when. In Wireshark,
filter `btatt.opcode == 0x52 || btatt.opcode == 0x12` (write command / write request)
and read the payloads. Brightness 1 vs 2 differs in one byte, and that byte is the
brightness field. That discipline is what makes this tractable.

## Step 5 — replay and confirm

```sh
python3 tools/ledhat_gatt.py <ADDRESS> --write 0000fff1-0000-1000-8000-00805f9b34fb --hex 01020304
```

Replay a captured frame verbatim first. Once a captured frame reproduces its effect,
start mutating single bytes to map the fields.

## Legal note

Reverse engineering a device you own, for interoperability, is what these steps are
for. That is a well-established use — it is the same work behind every driver linked
above. Don't redistribute the vendor's APK or its assets.
