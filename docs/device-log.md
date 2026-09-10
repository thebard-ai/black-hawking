# Device log

Findings for the specific hardware in hand. Method lives in
[`protocol-notes.md`](protocol-notes.md); this file is the record of what we saw.

## Scan, 2026-09-10 (macOS, `--all`, 20s)

Eleven devices in range. Nine were immediately excludable: manufacturer ID `0x004c`
(Apple) on seven, `0x0075` (Samsung) on one, and a named iPad. Two candidates:

### `DSD-3AF2B6` — the LED hat, CONFIRMED

Confirmed 2026-09-10 by `ledhat_scan.py --ab`: of eleven devices in range, this was
the only one present before powering the hat off and absent after.

Advertisement: service `0000fee9`, manufacturer `0x5254` payload `0027`, ~-66 dBm.
(`0x5254` is not a SIG-assigned company ID; cheap boards routinely put junk in that
field, so it carries no information.)

GATT tree:

```
service 0000fee9  Quintic Corp.
  d44bc439-abfd-45a2-b575-925416129600  [write, write-without-response]
  d44bc439-abfd-45a2-b575-92541612960a  [write, write-without-response]
  d44bc439-abfd-45a2-b575-92541612960b  [write, write-without-response]
  d44bc439-abfd-45a2-b575-925416129601  [notify]
service 0000ae00  vendor
  0000ae01  [write-without-response]
  0000ae02  [notify]
```

This is a **Quintic/NXP QN902x board running QPPS** — the Queued Packet Protocol
Service, NXP's generic serial-over-BLE transport, documented in
[AN11846](https://www.nxp.com/docs/en/application-note/AN11846.pdf). The
`d44bc439-…-9254161296xx` range is the stock QPP characteristic set: `…9600` writes
to the device, `…9601` notifies back. The `ae00/ae01/ae02` service is the same
vendor's second serial channel ("QN protocol").

What this means for us: **QPP is a pipe, not a protocol.** It carries whatever frames
the vendor's firmware defines, so the transport being documented buys us the
addressing but none of the semantics. The command encoding still has to come from the
app (see step 3 in the protocol notes).

On subscribing, `…9601` immediately pushed 16 bytes of high-entropy data:

```
41 bc 78 32 ed 1c 5b bc 5f 8e fb 97 13 6a 7d 59
```

Sixteen random-looking bytes unprompted on connect looks like a challenge/nonce,
which would mean an authentication handshake before the device accepts commands.
Not yet confirmed — it could equally be an opaque status blob. Worth re-reading on a
second connection: a value that **changes per connection** is a nonce, one that stays
**identical** is a device identifier or status.

Pressing the hat's mode button during a 20s listen produced no further notifications.

### `(no name)` @ -56 dBm — ruled out

Advertised nothing but a strong signal, but the GATT tree settles it: service `0000fe2c`
is **Google Fast Pair**, alongside `0000fd90` (Google) and a placeholder
`66666666-…`/`77777777-…` OTA service. Fast Pair is an audio-accessory and
find-my-device protocol; LED hats do not implement it. Its notify characteristic also
demands encryption (`CBATTErrorDomain Code=15`), i.e. it wants bonding — consistent
with earbuds, not a display. Almost certainly a neighbour's earbuds.

## Open questions

1. ~~Is `DSD-3AF2B6` actually the hat?~~ **Confirmed** by power-cycle A/B.
2. **Is the 16-byte notify a nonce?** Run `ledhat_gatt.py <addr> --probe`, which
   connects three times and compares the opening payload. Changing per connection
   means an auth handshake stands between us and the display commands; fixed means
   it is an identifier we can ignore.
3. **Which write characteristic takes display commands?** `…9600`, `…960a`, `…960b`
   and `ae01` are four candidate sinks. The app's own frames will say which.
