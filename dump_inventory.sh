#!/bin/bash
# Read-only inventory dump of a Zimbra/Carbonio mailstore. Run as the service user.
# Usage: bash -s <ZROOT>   e.g. /opt/zimbra or /opt/zextras
set -u
ZROOT="$1"
M="$ZROOT/bin/mysql"
OUT=/tmp/claude_inv
mkdir -p "$OUT"
echo "host=$(hostname -f) start=$(date -Is)"
"$M" -N -B -e "select id, group_id, account_id, comment from zimbra.mailbox" > "$OUT/mailboxes.tsv"
echo "mailboxes=$(wc -l < "$OUT/mailboxes.tsv")"
"$M" -N -B -e "select id,name,path,type from zimbra.volume" > "$OUT/volumes.tsv"
: > "$OUT/mail_item.tsv"
for g in $("$M" -N -B -e "show databases like 'mboxgroup%'"); do
  "$M" -N -B -e "select mailbox_id,id,type,parent_id,folder_id,date,size,ifnull(locator,''),ifnull(blob_digest,''),unread,flags,ifnull(tag_names,''),ifnull(sender,''),ifnull(name,''),ifnull(subject,''),mod_content,change_date from $g.mail_item where type in (1,5,13)" >> "$OUT/mail_item.tsv" 2>>"$OUT/errors.log"
  "$M" -N -B -e "select count(*) from $g.mail_item_dumpster where type=5" 2>/dev/null | sed "s/^/$g dumpster /" >> "$OUT/dumpster_counts.txt"
done
echo "rows=$(wc -l < "$OUT/mail_item.tsv") messages=$(awk -F'\t' '$3==5' "$OUT/mail_item.tsv" | wc -l) folders=$(awk -F'\t' '$3==1' "$OUT/mail_item.tsv" | wc -l)"
gzip -f "$OUT/mail_item.tsv"
echo "errors=$(wc -l < "$OUT/errors.log" 2>/dev/null || echo 0) done=$(date -Is)"
ls -la "$OUT"
