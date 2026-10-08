#!/bin/bash
# Run ON THE SOURCE mailstore as the service user (zimbra/zextras).
# Reads a restore TSV (from diff_inventory.py --export) on stdin, resolves each
# message to its blob on disk, and writes a tar of those blobs to stdout as
# <mailbox_id>/<item_id>.msg.  Pipe it to the destination, e.g.
#   restore_fetch.sh /opt/zextras < list.tsv | ssh dest 'tar xf - -C /tmp/restore'
#
# Blob path layout (FileBlobStore):
#   <volume>/<(mbox >> mailbox_bits) & (2^mailbox_group_bits - 1)>/<mbox>/msg/
#            <(item >> file_bits) & (2^file_group_bits - 1)>/<item>-<mod_content>.msg
# The bit widths come from zimbra.volume (defaults 12/8/12/8).  The group mask
# matters: with file_group_bits=8 the directory index wraps every 2^20 items,
# so item 1048576 lives in msg/0, not msg/256.
set -u
ZROOT="$1"
M="$ZROOT/bin/mysql"
LIST=$(mktemp); MISSING=/tmp/restore_fetch_missing.txt; : > "$MISSING"
declare -A VPATH VFB VFGB VMB VMGB
while IFS=$'\t' read -r id path fb fgb mb mgb; do
  VPATH[$id]="$path"; VFB[$id]="$fb"; VFGB[$id]="$fgb"; VMB[$id]="$mb"; VMGB[$id]="$mgb"
done < <("$M" -N -B -e "select id,path,file_bits,file_group_bits,mailbox_bits,mailbox_group_bits from zimbra.volume")
tail -n +2 | while IFS=$'\t' read -r acct mbox item modc locator folder rest; do
  v="${locator:-1}"
  vol="${VPATH[$v]:-$ZROOT/store}"; fb="${VFB[$v]:-12}"; fgb="${VFGB[$v]:-8}"; mb="${VMB[$v]:-12}"; mgb="${VMGB[$v]:-8}"
  mdir=$(( (mbox >> mb) & ((1 << mgb) - 1) ))
  idir=$(( (item >> fb) & ((1 << fgb) - 1) ))
  f="$vol/$mdir/$mbox/msg/$idir/$item-$modc.msg"
  if [ -f "$f" ]; then printf '%s\n' "$f"; else echo "$acct $mbox $item $f" >> "$MISSING"; fi
done > "$LIST"
echo "fetch: $(wc -l < "$LIST") blobs found, $(wc -l < "$MISSING") not on disk (see $MISSING)" >&2
# --transform renames <vol>/<g>/<mbox>/msg/<d>/<item>-<modc>.msg -> <mbox>/<item>.msg
tar cf - --absolute-names -T "$LIST" --transform='s|^.*/\([0-9]*\)/msg/[0-9]*/\([0-9]*\)-[0-9]*\.msg$|\1/\2.msg|' 2>/dev/null
rm -f "$LIST"
