#!/usr/bin/env bash
# Export the Katana's command-channel traffic from iOS Bluetooth logs (.pklg) as
# frames.tsv: epoch <TAB> ATT opcode <TAB> handle <TAB> value (hex), duplicates removed (a
# sysdiagnose holds overlapping rotated logs) and sorted as whole lines -- the epochs have equal
# width, so that is time order, with a notification ahead of a command in the same millisecond.
#
#   tools/pklg_to_tsv.sh out.tsv bluetoothd-hci-*.pklg
#
# Commands: ATT Write Command 0x52 to handle 0x000b. Replies: Notification 0x1b
# from 0x0008. Only frames that start with the 5A marker are kept.
set -euo pipefail
out=$1; shift
for f in "$@"; do
  tshark -r "$f" -Y 'btatt.opcode == 0x52 || btatt.opcode == 0x1b' \
    -T fields -e frame.time_epoch -e btatt.opcode -e btatt.handle -e btatt.value 2>/dev/null
done | awk -F'\t' '($3 == "0x000b" || $3 == "0x0008") && $4 ~ /^5a/' | sort -u > "$out"
wc -l < "$out"
