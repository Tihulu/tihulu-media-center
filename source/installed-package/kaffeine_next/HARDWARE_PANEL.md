# Native Hardware tab · USB / RTL-SDR / DVB-T2

**TIHULU Media Center → Hardware** (or Start → **8 Hardware and receiver ownership**).

This native Qt5 tab uses the optional Python companion command:

```sh
tihulu-tv-center hardware-status
tihulu-tv-center hardware-status --owners
```

The first command is **read-only**. It enumerates kernel USB sysfs devices,
selects likely radio/TV receivers (including RTL2832/RTL2838 and Hauppauge
USB devices), and enumerates registered `/dev/dvb/adapter*/frontend*`
nodes, if present. It reports the USB ID/name, Linux node and current
user's read/write permission. It **does not open or test reception**. DVB
registration does not prove antenna lock, and USB detection does not prove
the kernel driver or RF software can operate the device.

The second command is **optional** and runs bounded, read-only
`fuser -v -- <device>` queries on DVB frontends and probable SDR USB nodes.
`fuser` may show process IDs that own the frontend. Lack of visible PIDs
is **not proof of exclusive access**, especially without privilege. The app
does not run `sudo`, kill competing programs or reset a USB bus.

## Live controls

- **Refresh devices now**: one immediate inventory, no tuner claim.
- **Watch USB plug / unplug**: opt-in sampling every 2.5 seconds. Event
  history shows detected connections and removals. Turning this off stops
  the polling; physical devices remain untouched.
- **Receiver devices only**: filter inventory without deleting entries.
- **Check DVB/SDR owners**: optional, read-only OS process check.
- **Attach/start DAB**: starts *TIHULU's* welle-cli process on the Radio tab's
  selected block. It may release *TIHULU's* analog rtl_fm process; permission
  prompt is shown before switching.
- **Release TIHULU DAB**: stops only the radio tab's owned welle-cli and
  captions/recording workers.
- **Attach/play selected FM** and **Release TIHULU analogue SDR**:
  reuse the native Radio tab frequency and bounded process management;
  no arbitrary USB unbind. Choose the band/frequency on Radio first.
- **Open TV / tune last channel**: navigates to the native Television tab
  and optionally reacquires DVB by tuning its remembered channel.
  No blind full-band scan is performed.
- **Stop TV / release playback**: stops live playback only when this
  Kaffeine session has a DVB live-view device. **Active recordings are
  protected**; no force-close of tuner or recording.

An ordinary Linux process cannot emulate physical unplugging. To unplug
a stick, release the worker first and physically remove it. The watcher
will then show the disappearance when enabled.

## Diagnosing the supplied symptoms

- `Analog SDR exited (1)` means rtl_fm failed. Hardware may still be
  **present**: inspect USB ID and permissions, then click read-only owners
  and check whether another SDR application is using the same USB device.
  No claim is made that a driver or USB permission change fixes it.
- `Cannot tune: local welle receiver API is unreachable` is different:
  welle-cli may exit, be waiting on the SDR, or its localhost API may not
  be ready. Hardware shows the native worker PID, API-ready state, port
  and captured stderr/exit code. Restarting a receiver is an explicit
  action; no hidden worker is launched by the inventory tab.
- `11D actual SNR 0.0 dB` means the receiver reported a poor/uncertain
  DAB signal, **not** automatically a disconnected physical device.
- A DVB frontend visible at `/dev/dvb/adapter0/frontend0` does not
  prove the live image or tuning will work. Existing DVB scan and
  decoder diagnostics remain separate.

## Verification

CI covers Python 3.11–3.13 read-only discovery and synthetic USB/DVB
fixtures, the pinned Kaffeine native build, and the Debian preview.
Only tests on the user's actual Hauppauge/Si2168 and RTL-SDR device
can confirm USB hotplug notifications, successful DAB playback, channel
scanning, analog volume, RF lock or device release.

This is part of draft PR #38, not merged to `main`.
