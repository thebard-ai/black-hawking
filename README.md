# black-hawking

Talking to a BLE LED display hat without the vendor's app.

## Should you install the vendor APK?

Short version: **not on your daily-driver phone.**

This is not "Chinese app therefore spyware." The specific problems with this class of
app are concrete and well documented:

- It is **sideloaded from a vendor URL**, not from Play. No Play Protect scanning, no
  store review, no signature accountability, and it will ask for permission to install
  further packages.
- Apps in this family (e.g. Magic Display, `com.tirohk.magicdisplay`) draw consistent
  user reports of **permission requests unrelated to their function** — contacts,
  location, storage — for something whose entire job is to push a bitmap over BLE.
- Android grants **location permission as a prerequisite for BLE scanning**, so a badly
  behaved LED app gets your position legitimately and can exfiltrate it.
- These apps are built by small OEM shops on top of shared, ad-laden SDKs, and they
  update outside any store review process.

Reasonable options, in order:

1. **Reverse the protocol and skip the app entirely.** This repo. The device is a dumb
   BLE peripheral; the app is a bitmap encoder with a UI.
2. **Burner device.** Old phone, no SIM, no Google account, no personal data, Wi-Fi off
   after install. Fine, and it's also how you capture the protocol (see step 3 below).
3. **Install on your daily phone.** Only if you want the product to just work today and
   accept the data exposure.

## Should you expect to be able to reverse it?

Yes. This is a well-trodden path — several of these OEM boards already have complete
open-source drivers, and you may not have to write any protocol code at all. The whole
family is one write characteristic taking framed bytes.

Realistic effort:

- **5 minutes** if the hat turns out to be a known family (CoolLEDX, iDotMatrix, B1248)
  — a driver already exists.
- **An evening** if it's an undocumented board but you can capture the app's Bluetooth
  traffic. Text and brightness first, images after.
- **A weekend** if the frames are checksummed or the image encoding is non-obvious.

## Start here

```sh
pip install -r requirements.txt
python3 tools/ledhat_scan.py --seconds 15
```

Power the hat on, **unplug it from USB**, close the vendor app, then run the scan. The
advertised device name tells you which family you have and whether a driver already
exists.

Then:

```sh
python3 tools/ledhat_gatt.py <ADDRESS> --listen 30
```

## Contents

| Path | What it does |
|---|---|
| `tools/ledhat_scan.py` | BLE scan; fingerprints devices against known LED protocol families |
| `tools/ledhat_gatt.py` | Connect, dump the GATT tree, log notifications, replay raw frames |
| `docs/protocol-notes.md` | Known families, HCI snoop capture workflow, APK static analysis |

Full workflow, including how to capture the vendor app's Bluetooth traffic on a burner
device: [`docs/protocol-notes.md`](docs/protocol-notes.md).
