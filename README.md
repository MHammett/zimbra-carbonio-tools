# zimbra-carbonio-tools

Find and restore messages that a Zimbra or Carbonio migration silently dropped.

Both products keep each mailbox as rows in a per-mailbox-group MySQL/MariaDB
database (`mboxgroupN.mail_item`) plus one raw RFC 822 file per message under
the store directory. Every message row carries a `blob_digest`, the hash of
that raw file. A migration that copies messages byte-for-byte (Zextras backup
and restore, `zmmailbox` export/import, most IMAP-based tools) produces the
same digest on both servers, so the digest can be used as a key to diff two
servers and find exactly which messages never arrived, without parsing a
single message.

These scripts were written to clean up after a chain of migrations
(Zimbra 8.8 cluster → Carbonio → Carbonio) that lost tens of thousands of
messages in a handful of mailboxes while reporting success. They found the
losses in an afternoon and put the messages back with their original folder,
received date, flags, unread state and tags.

## The method

1. **Inventory** each server with `dump_inventory.sh`. Read-only. Needs only
   the service user and the local database; on a retired server you can
   start just the bundled MySQL (`mysql.server start` as `zimbra`) and leave
   LDAP and mailboxd down.
2. **Diff** the inventories with `diff_inventory.py`. The overlap percentage
   it prints tells you whether the digest is a usable key. Above about 90 %
   it is. Far below that the migration rewrote message bytes and you would
   need a Message-ID based comparison instead, which this repo does not do.
3. **Export** the missing set to a TSV with `--export`. By default it leaves
   out Trash and Junk and the system accounts (`zextras`, `admin`, spam/ham
   training, virus quarantine, galsync); override with `--skip-folders` and
   `--skip-accounts`.
4. **Fetch** the raw files on the source with `restore_fetch.sh`, which
   streams them as a tar to wherever you point it.
5. **Import** on the destination with `restore_import.py`, which drives
   `zmmailbox addMessage` once per account from a command file and tags every
   restored message so the batch can be reviewed or removed later.
6. **Re-inventory the destination and diff again** to confirm the gap is
   closed. Restored messages are byte-identical, so they match by digest.

## Usage

On each server, as the service user (`zimbra` or `zextras`):

```bash
bash dump_inventory.sh /opt/zextras        # or /opt/zimbra
# writes /tmp/claude_inv/{mailboxes.tsv,volumes.tsv,mail_item.tsv.gz,dumpster_counts.txt}
```

Copy each server's `/tmp/claude_inv` to a directory per server on your
workstation, then:

```bash
python diff_inventory.py inv/old-server inv/production --folders
python diff_inventory.py inv/old-server inv/production --export=restore.tsv
```

Source server, streaming straight to the destination (the source needs SSH
access to the destination, or pipe through your workstation):

```bash
bash restore_fetch.sh /opt/zextras < restore.tsv \
  | ssh zextras@production 'mkdir -p /tmp/restore && tar xf - -C /tmp/restore'
```

Destination, as the service user. Try one account with a limit first:

```bash
python3 restore_import.py restore.tsv /tmp/restore --only=someone@example.com --limit=200
python3 restore_import.py restore.tsv /tmp/restore --tag=Restored-2026-10
```

`restore.tsv.result.tsv` records the new item id, or a blank, for every row,
so a failed batch can be retried by filtering the list.

## Things worth knowing

- **Message counts in `mail_item` include duplicates.** The same message in
  two folders is two rows with one digest. The diff works on distinct digests.
- **A message in Trash on the source and absent on the destination is more
  likely a deletion than a loss.** That is why Trash and Junk are excluded by
  default. Nothing in the database distinguishes "never migrated" from
  "deleted after migrating" once the dumpster has expired it.
- **`tag_names` is NUL-delimited** in the database and the mysql client
  writes each NUL as the two characters `\0`. The importer splits on that.
- **Flags** are the Zimbra bitmask (`1` from me, `4` replied, `8` forwarded,
  `32` flagged, `64` draft, `1024` high priority, `2048` low priority);
  `unread` is a separate column. The importer translates both to the letter
  flags `zmmailbox` expects. The attachment bit is recomputed on import.
- **`zmmailbox -f`** echoes its prompt before every command and answers
  `addMessage` with `<new id> (<file>)`. `createFolder` on an existing folder
  prints `mail.ALREADY_EXISTS`, which is harmless; the importer ignores it.
- **Blob path layout** is
  `<volume>/<(mailbox_id >> 12) & 255>/<mailbox_id>/msg/<(item_id >> 12) & 255>/<item_id>-<mod_content>.msg`
  with the bit widths taken from `zimbra.volume` (`file_bits`,
  `file_group_bits`, `mailbox_bits`, `mailbox_group_bits`). The group mask
  matters: the directory index wraps every 2^20 items, so item 1048576 is in
  `msg/0`, not `msg/256`. A busy alerts mailbox crosses that line in a few
  years, and without the mask every later message looks missing from disk.
- **Throughput** depends on the target mailbox. Into a small mailbox a
  single `zmmailbox` session adds 10 to 15 messages a second; into one
  that already holds hundreds of thousands of messages each add takes close
  to a second server-side. The mailbox server scales across sessions, so
  split a big account's list into chunks (`head`/`sed` on the TSV, keep the
  header) and run several importers at once: four sessions gave about three
  times the single-session rate with no lock failures on an 8-core box.
- **Turn off conversation threading on the target account before a bulk
  import of alert or notification mail.** Each add joins the message to a
  subject-threaded conversation and reloads every message already in it
  to recalculate metadata (`Conversation.addChild` ->
  `DbMailItem.getByParent`). Repeated subjects make that cost grow with
  every message, so the import decays: 1,730 -> 1,130 adds per five
  minutes over twelve hours into one alerts mailbox. Setting
  `zmprov ma user@example.com zimbraMailThreadingAlgorithm none` on just
  that account took it to 10,200 per five minutes immediately. Put it
  back afterwards with
  `zmprov ma user@example.com -zimbraMailThreadingAlgorithm none`, which
  restores inheritance from the class of service. A thread dump
  (`jcmd <mailboxd pid> Thread.print`) is how to find this kind of thing.
- **Pause IMAP clients on the target mailbox** during a large import. A
  phone client that re-runs a folder search after every batch can hold the
  mailbox lock for minutes at a time and stall the import to a crawl.

## Several old servers

When more than one old server holds copies, diff and export each against
production, then run `merge_exports.py OUT a.tsv b.tsv ...` with the inputs
in order of preference (newest copy first). Each output keeps only the rows
no earlier input claimed, so every message is fetched and imported once.
Keep a separate blob directory per source on the destination, because
mailbox ids collide across servers.

## Helpers

- `queue_summary.py` summarises a large Postfix queue from `postqueue -j`
  on stdin: counts by queue, recipient and sender domains, age range,
  delay reasons. Useful for telling real stuck mail from cron noise on a
  retired server.
- `import_dates.py` reads one inventory and shows when each domain's
  messages were last changed, which exposes when a server was populated
  by an import.

## Status

Used in October 2026 against Zimbra 8.8.15 (Ubuntu 16.04) and Carbonio CE
on Ubuntu 22.04 and 24.04. Reads use the `mysql` client bundled with the
product; writes go only through `zmmailbox`, never the database.
