#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Read-only DVB receiver diagnostics. Does not stop processes or retune devices.
set -u
printf 'TIHULU Media Center · DVB frontend diagnostics\n'
printf 'User: %s | Groups: %s\n' "$(id -un)" "$(id -nG)"
printf 'Date: %s\n\n' "$(date --iso-8601=seconds)"
shopt -s nullglob
# A valid device is not enough: Kaffeine matches channel.source against the
# configured DVB device's EXACT Source name. Inspect both independent TIHULU
# and pre-migration Kaffeine storage without modifying or leaking device IDs.
printf 'Saved television Source names (read-only):\n'
found_config=0
for config in "$HOME/.local/share/tihulu-media-center/config.dvb" \
              "$HOME/.local/share/kaffeine/config.dvb"; do
  if [[ ! -f "$config" || ! -r "$config" ]]; then continue; fi
  found_config=1
  printf '  Database: %s\n' "$config"
  awk -F= '
    /^\[device\]$/ { print "    [device]"; next }
    /^\[config\]$/ { print "    [config]"; next }
    /^(frontendName|name|scanSource)=/ {
      key=$1
      # Do not show sensitive serial/device-ID settings, just display names.
      sub(/^[^=]*=/,"",$0)
      print "      " key ": " substr($0,1,160)
    }
  ' "$config"
done
if (( found_config == 0 )); then
  printf '  No saved device Source configuration found in either directory.\n'
fi
printf '\n'
frontends=(/dev/dvb/adapter*/frontend*)
if (( ${#frontends[@]} == 0 )); then
  printf 'No /dev/dvb/adapter*/frontend* devices found. Check USB, kernel driver and firmware.\n'
  exit 0
fi
for frontend in "${frontends[@]}"; do
  printf 'Frontend: %s\n' "$frontend"
  ls -l -- "$frontend" || true
  if [[ -r "$frontend" && -w "$frontend" ]]; then
    printf '  Permissions: user can read and write\n'
  else
    printf '  Permissions: missing read/write access; check video group and udev rules\n'
  fi
  if command -v fuser >/dev/null 2>&1; then
    # A player/scanner may hold demux0 or dvr0 while the frontend
    # file alone looks free. Inspect all nodes of this same DVB adapter.
    owners="$(fuser -- "${frontend%/*}"/* 2>/dev/null || true)"
    if [[ -n "$owners" ]]; then
      printf '  DVB adapter OPEN by PID(s): %s\n' "$owners"
      for pid in $owners; do
        case "$pid" in
          *[!0-9]*|'') continue ;;
        esac
        ps -p "$pid" -o pid=,comm=,args= || true
      done
    else
      printf '  No owner visible to this user (permission limits may hide another process).\n'
    fi
  else
    printf '  fuser unavailable (install psmisc to inspect process ownership).\n'
  fi
  if command -v udevadm >/dev/null 2>&1; then
    udevadm info --query=property --name="$frontend" 2>/dev/null |
      grep -E '^(ID_VENDOR_ID|ID_MODEL_ID|ID_MODEL|DEVNAME)=' || true
  fi
  printf '\n'
done
printf 'A busy frontend cannot be used by two independent programs.\n'
printf 'Exit the other TV/SDR application normally; do not kill arbitrary processes.\n'
printf 'A detected DVB frontend with read/write permission is not proof of RF lock.\n'
printf 'TIHULU defaults an UNCONFIGURED DVB-T2 frontend to native AUTO-T2-Normal.\n'
printf 'If you previously saved No Source, change it explicitly to AUTO-T2-Normal or a suitable regional list.\n'
printf 'Then run Television > Full Antenna Scan; inspect live lock/SNR in the scan UI.\n'
printf 'DAB Band III scanning is separate from DVB-T2 and needs a compatible SDR/welle receiver.\n'