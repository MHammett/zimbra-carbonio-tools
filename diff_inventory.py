#!/usr/bin/env python3
"""Compare two mailstore inventories produced by dump_inventory.sh.

    python diff_inventory.py SRC_DIR DST_DIR [options]

Reports, for every account present on both servers, the messages on SRC
(keyed by blob_digest) that are absent on DST.  The digest is the SHA of
the raw blob, so a message copied byte-for-byte has the same digest on
both sides and one rewritten by a migration tool does not.  The overlap
percentage tells you which case you are in; above ~90 % the digest is a
usable key, far below it you need a Message-ID based comparison instead.

Options
  --per-account         list every shared account, not just the top 25
  --folders             show the folders the missing messages sit in
  --export=FILE         write the missing messages as TSV for restore_*.sh
  --skip-folders=A,B    top-level folders to leave out of the export
                        (default Trash,Junk; pass --skip-folders= for none)
  --skip-accounts=RE    accounts to leave out of the export, regex on the
                        address (default: zextras, admin, spam/ham training,
                        virus-quarantine and galsync accounts); pass an
                        empty value for none
  --only=a@x,b@x        export only these accounts
"""
import collections
import csv
import datetime
import gzip
import os
import re
import sys

csv.field_size_limit(1 << 30)
SYSTEM_FOLDERS = {2: "Inbox", 3: "Trash", 4: "Junk", 5: "Sent", 6: "Drafts", 7: "Contacts",
                  10: "Calendar", 13: "Emailed Contacts", 14: "Chats", 16: "Briefcase"}
DEFAULT_SKIP_ACCOUNTS = r"^(zextras|admin|spam\.|ham\.|virus-quarantine\.|galsync\.)"

# mail_item.tsv columns written by dump_inventory.sh
(C_MBOX, C_ID, C_TYPE, C_PARENT, C_FOLDER, C_DATE, C_SIZE, C_LOCATOR, C_DIGEST,
 C_UNREAD, C_FLAGS, C_TAGS, C_SENDER, C_NAME, C_SUBJECT, C_MODC, C_CHANGE) = range(17)


class Msg:
    __slots__ = ("iid", "folder", "date", "size", "flags", "subject", "sender",
                 "unread", "tags", "locator", "modc")

    def __init__(self, r):
        self.iid = int(r[C_ID]); self.folder = int(r[C_FOLDER]); self.date = int(r[C_DATE])
        self.size = int(r[C_SIZE]); self.flags = int(r[C_FLAGS]); self.subject = r[C_SUBJECT][:80]
        self.sender = r[C_SENDER][:60]; self.unread = int(r[C_UNREAD] or 0); self.tags = r[C_TAGS]
        self.locator = r[C_LOCATOR]; self.modc = int(r[C_MODC] or 0)


def load(d):
    """Return {email: {"mbid", "folders", "parent", "msgs": {digest: Msg}}}."""
    boxes = {}
    with open(os.path.join(d, "mailboxes.tsv"), encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            boxes[int(row[0])] = row[3].lower()
    acct = {e: {"mbid": m, "folders": {}, "parent": {}, "msgs": {}} for m, e in boxes.items()}
    by_mb = {m: acct[e] for m, e in boxes.items()}
    with gzip.open(os.path.join(d, "mail_item.tsv.gz"), "rt", encoding="utf-8",
                   errors="replace", newline="") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(row) < 17:
                continue
            a = by_mb.get(int(row[C_MBOX]))
            if a is None:
                continue
            t = int(row[C_TYPE])
            if t == 1:
                iid = int(row[C_ID])
                a["folders"][iid] = row[C_NAME]
                a["parent"][iid] = int(row[C_PARENT]) if row[C_PARENT] else 0
            elif t == 5:
                dg = row[C_DIGEST] or f"nodigest:{row[C_MBOX]}:{row[C_ID]}"
                a["msgs"].setdefault(dg, Msg(row))
    return acct


def fpath(a, fid):
    parts = []
    seen = 0
    while fid and fid != 1 and seen < 20:
        parts.append(a["folders"].get(fid, SYSTEM_FOLDERS.get(fid, f"#{fid}")))
        fid = a["parent"].get(fid, 0)
        seen += 1
    return "/".join(reversed(parts)) or "/"


def opt(name, default=None):
    for x in sys.argv[1:]:
        if x.startswith(name + "="):
            return x.split("=", 1)[1]
    return default


def year(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).year


def export(src, dst, path):
    skip_folders = set(opt("--skip-folders", "Trash,Junk").split(",")) - {""}
    pat = opt("--skip-accounts", DEFAULT_SKIP_ACCOUNTS)
    skip_accounts = re.compile(pat, re.I) if pat else None
    only = set(opt("--only", "").split(",")) - {""}
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as out:
        out.write("\t".join(["account", "src_mailbox_id", "item_id", "mod_content", "locator", "folder",
                             "date", "flags", "unread", "tags", "size", "digest", "subject"]) + "\n")
        for e, a in sorted(src.items()):
            if e not in dst or (only and e not in only) or (skip_accounts and skip_accounts.search(e)):
                continue
            for k, m in a["msgs"].items():
                if k in dst[e]["msgs"]:
                    continue
                fp = fpath(a, m.folder)
                if fp.split("/")[0] in skip_folders:
                    continue
                out.write("\t".join(str(x) for x in (
                    e, a["mbid"], m.iid, m.modc, m.locator, fp, m.date, m.flags, m.unread, m.tags,
                    m.size, k, m.subject.replace("\t", " "))) + "\n")
                n += 1
    print(f"exported {n:,} missing messages to {path}")
    print(f"  skipped top-level folders: {sorted(skip_folders)}; skipped accounts matching: {pat or None}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        sys.exit(2)
    per_account = "--per-account" in sys.argv
    folders = "--folders" in sys.argv
    src, dst = load(args[0]), load(args[1])
    if opt("--export"):
        export(src, dst, opt("--export"))
        return
    print(f"SRC {args[0]}: {len(src)} accounts, {sum(len(a['msgs']) for a in src.values()):,} distinct messages")
    print(f"DST {args[1]}: {len(dst)} accounts, {sum(len(a['msgs']) for a in dst.values()):,} distinct messages")
    missing_acct = sorted(e for e in src if e not in dst)
    print(f"accounts on SRC but not DST: {len(missing_acct)}")
    for e in missing_acct:
        print(f"   {e}  ({len(src[e]['msgs']):,} msgs)")
    tot_src = tot_missing = tot_bytes = 0
    rows = []
    yr = collections.Counter()
    fold = collections.Counter()
    for e, a in sorted(src.items()):
        if e not in dst:
            continue
        b = dst[e]
        miss = [m for k, m in a["msgs"].items() if k not in b["msgs"]]
        tot_src += len(a["msgs"]); tot_missing += len(miss); tot_bytes += sum(m.size for m in miss)
        nojunk = [m for m in miss if m.folder not in (3, 4)]
        rows.append((len(miss), len(nojunk), e, len(a["msgs"]), len(b["msgs"]), sum(m.size for m in miss)))
        for m in miss:
            yr[year(m.date)] += 1
            if folders:
                fold[(e, fpath(a, m.folder))] += 1
    ov = 100.0 * (tot_src - tot_missing) / tot_src if tot_src else 0
    print(f"\nshared accounts: {len(rows)}  SRC msgs {tot_src:,}  present on DST by digest "
          f"{tot_src - tot_missing:,} ({ov:.1f}%)  MISSING {tot_missing:,} ({tot_bytes / 1e9:.2f} GB)")
    print("missing by year:", " ".join(f"{y}:{c:,}" for y, c in sorted(yr.items())))
    print(f"\n{'missing':>8} {'excl junk/trash':>15} {'src':>9} {'dst':>9} {'MB':>7}  account")
    for n, nj, e, s, dd, by in sorted(rows, reverse=True)[:(len(rows) if per_account else 25)]:
        if n == 0 and not per_account:
            break
        print(f"{n:8,} {nj:15,} {s:9,} {dd:9,} {by / 1e6:7.0f}  {e}")
    if folders:
        print("\ntop folders with missing messages:")
        for (e, p), c in fold.most_common(40):
            print(f"{c:8,}  {e}  {p}")


if __name__ == "__main__":
    main()
