#!/usr/bin/env bash
# Optional user-run RTL-SDR / Linux DVB driver ownership helper.
# STATUS (default) is read-only. RELEASE / RESTORE require explicit action.
# No automatic service stop, device takeover, driver blacklist or udev edit.
set -euo pipefail
mode="${1:-status}"
device_filter="${2:-}"
if [[ ! "$mode" =~ ^(status|release|restore)$ ]]; then
  echo "Usage: $0 [status|release|restore] [USB-ID e.g. 1-4]" >&2
  exit 2
fi
if [[ -n "$device_filter" && ! "$device_filter" =~ ^[0-9]+-[0-9]+(\.[0-9]+)*$ ]]; then
  echo "Invalid USB-ID; use the bus/port ID from status output, e.g. 1-4" >&2
  exit 2
fi

declare -a matches=()
for dev in /sys/bus/usb/devices/*; do
  [[ -f "$dev/idVendor" && -f "$dev/idProduct" ]] || continue
  [[ "$(<"$dev/idVendor")" == "0bda" &&
     "$(<"$dev/idProduct")" == "2838" ]] || continue
  id="${dev##*/}"
  [[ -z "$device_filter" || "$id" == "$device_filter" ]] || continue
  for iface in "$dev":*.0; do
    [[ -d "$iface" ]] || continue
    matches+=("$iface")
  done
done
if (( ${#matches[@]} == 0 )); then
  echo "No RTL2832U USB interface 0 (0bda:2838) found." >&2
  exit 1
fi
if (( ${#matches[@]} != 1 )); then
  echo "Multiple RTL-SDR interfaces found. Specify one USB-ID:" >&2
  printf '  %s\n' "${matches[@]##*/}" >&2
  echo "Example: $0 status 1-4" >&2
  exit 2
fi
iface_path="${matches[0]}"
iface_name="${iface_path##*/}"
usb_id="${iface_name%%:*}"
driver_link="$iface_path/driver"
current="none"
if [[ -L "$driver_link" ]]; then
  current="$(basename "$(readlink -f "$driver_link")")"
fi
echo "Receiver: 0bda:2838 | USB path: $usb_id | interface: $iface_name"
echo "Kernel driver: $current"
if command -v systemctl >/dev/null 2>&1; then
  state="$(systemctl is-active readsb.service 2>/dev/null || true)"
  echo "readsb.service: ${state:-unknown} (never stopped automatically)"
fi

if [[ "$mode" == "status" ]]; then
  echo "Read-only. Browser WebUSB requires an unclaimed RTL-SDR interface."
  exit 0
fi
if [[ "$mode" == "release" ]]; then
  if [[ "$current" == "none" ]]; then
    echo "Interface already has no kernel driver. No change."
    exit 0
  fi
  if [[ "$current" != "dvb_usb_rtl28xxu" ]]; then
    echo "Refusing to detach unexpected driver: $current" >&2
    exit 3
  fi
  echo "Releasing only $iface_name from $current for browser WebUSB."
  if (( EUID == 0 )); then
    printf '%s\n' "$iface_name" > "/sys/bus/usb/drivers/$current/unbind"
  else
    printf '%s\n' "$iface_name" | sudo tee "/sys/bus/usb/drivers/$current/unbind" >/dev/null
  fi
  [[ ! -L "$driver_link" ]] || { echo "Driver still bound." >&2; exit 4; }
  echo "Released. Do not replug the device; reconnecting may rebind the DVB driver."
  echo "Reload your HTTPS app and choose this receiver in Brave/Chrome/Edge."
  exit 0
fi

if [[ "$current" != "none" ]]; then
  echo "Already bound to $current; not changing a different driver."
  exit 0
fi
bind="/sys/bus/usb/drivers/dvb_usb_rtl28xxu/bind"
[[ -e "$bind" ]] || {
  echo "Driver bind path unavailable. No changes made." >&2
  exit 3
}
echo "Restoring DVB driver on $iface_name only; stop browser USB capture first."
if (( EUID == 0 )); then
  printf '%s\n' "$iface_name" > "$bind"
else
  printf '%s\n' "$iface_name" | sudo tee "$bind" >/dev/null
fi
echo "Restored driver: $(basename "$(readlink -f "$driver_link")")"
