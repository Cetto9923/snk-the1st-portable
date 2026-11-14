#!/usr/bin/env bash
# Launch existing installation without replacing resources or clearing logs.
set -euo pipefail
HONOR_SERIAL='A42BBB5109000333'
RG477M_SERIAL='RG477M01445122'
serial="${FFRS_DEVICE:-$HONOR_SERIAL}"
package='org.snk.the1st.gamewindow'
activity='org.snk.the1st.GameActivity'
root="$(cd "$(dirname "$0")/.." && pwd)"
logdir="$root/.local/logs/device-launch/$(date +%Y%m%d-%H%M%S)"
if [[ "$serial" != "$HONOR_SERIAL" && "$serial" != "$RG477M_SERIAL" ]]; then
    echo "BLOCKED_DEVICE: device $serial not supported (expected Honor: $HONOR_SERIAL, RG477M: $RG477M_SERIAL)" >&2
    exit 2
fi
mkdir -p "$logdir"
adb -s "$serial" get-state > "$logdir/device-state.log"
# An absent prior log is expected on a first launch.
adb -s "$serial" exec-out cat "/sdcard/Android/data/$package/files/guest_boot.log" > "$logdir/guest-boot-before.log" 2> "$logdir/prior-log-error.log" || true
adb -s "$serial" shell am force-stop "$package"
adb -s "$serial" shell am start -W -n "$package/$activity" > "$logdir/launch.log"
printf 'Launch evidence: %s\n' "$logdir"
