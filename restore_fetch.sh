#!/bin/bash
# Run ON THE SOURCE mailstore as the service user (zimbra/zextras).
# Reads a restore TSV (from diff_inventory.py --export) on stdin, resolves each
# message to its blob on disk, and writes a tar of those blobs to stdout as
# <mailbox_id>/<item_id>.msg.  Pipe it to the destination, e.g.
#   restore_fetch.sh /opt/zextras < list.tsv | ssh dest 'tar xf - -C /tmp/restore'
# Blob path layout: <volume>/<mbox>>12>/<mbox>/msg/<item>>12>/<item>-<mod_content>.msg
set -u
ZROOT="$1"
M="$ZROOT/bin/mysql"
LIST=$(mktemp); MISSING=/tmp/restore_fetch_missing.txt; : > "$MISSING"
declare -A VOL
while IFS=$'\t' read -r id name path type; do VOL[$id]="$path"; done < <("$M" -N -B -e "select id,name,path,type from zimbra.volume")
tail -n +2 | while IFS=$'\t' read -r acct mbox item modc locator folder rest; do
  vol="${VOL[${locator:-1}]:-$ZROOT/store}"
  f="$vol/$((mbox >> 12))/$mbox/msg/$((item >> 12))/$item-$modc.msg"
  if [ -f "$f" ]; then printf '%s\n' "$f"; else echo "$acct $mbox $item $f" >> "$MISSING"; fi
done > "$LIST"
echo "fetch: $(wc -l < "$LIST") blobs found, $(wc -l < "$MISSING") not on disk (see $MISSING)" >&2
# --transform renames <vol>/<g>/<mbox>/msg/<d>/<item>-<modc>.msg -> <mbox>/<item>.msg
tar cf - --absolute-names -T "$LIST" --transform='s|^.*/\([0-9]*\)/msg/[0-9]*/\([0-9]*\)-[0-9]*\.msg$|\1/\2.msg|' 2>/dev/null
rm -f "$LIST"
