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

The QR code on `api.e-toys.cn/page/app/64` is a vendor landing page that hands you an
APK plus an App Store link. The vendor site tells you nothing about the protocol; the
device's own BLE advertisement tells you everything you need to start.

## Step 1 — identify over the air

```sh
pip install -r requirements.txt
python3 tools/ledhat_scan.py --seconds 15
```

The hat must be powered on, **unplugged from USB** (most of these boards disable the
radio while charging), and not already connected to a phone.

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

## Step 3 — capture the vendor app's traffic

You do not need to decompile the APK to learn the protocol. You need the bytes it
sends. Use a **burner Android device** (see the risk note in the root README), then:

1. Developer options → **Enable Bluetooth HCI snoop log**.
2. Toggle Bluetooth off and on.
3. Drive the app: connect, set one pixel, set text, change brightness, change speed.
   Change **one variable at a time** and write down what you did and when.
4. Pull the log:
   ```sh
   adb bugreport bugreport.zip     # snoop log lives inside on modern Android
   # older devices: adb pull /sdcard/btsnoop_hci.log
   ```
5. Open in Wireshark, filter `btatt.opcode == 0x52 || btatt.opcode == 0x12`
   (write command / write request) and read the payloads.

The single-variable discipline is what makes this tractable: brightness 1 vs 2 differs
in one byte, and that byte is the brightness field.

## Step 4 — static analysis of the APK (only if step 3 stalls)

```sh
apktool d app.apk -o app_src          # resources, smali
jadx-gui app.apk                      # decompiled Java
```

Grep the decompiled source for the UUIDs you found in step 2. The class that
references the write characteristic is the protocol encoder. Chinese OEM apps of this
class are usually thin wrappers over a `BluetoothManager` helper with method names
like `sendText`, `sendPic`, `setBright` — often not obfuscated at all.

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
