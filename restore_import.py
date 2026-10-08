#!/usr/bin/env python3
"""Run ON THE DESTINATION mailstore as the service user (zimbra/zextras).

    python3 restore_import.py LIST.tsv BLOBDIR [--tag=NAME] [--limit=N] [--only=a@x,b@x] [--dry-run]

For every row of the restore TSV (from diff_inventory.py --export) whose blob
exists under BLOBDIR/<src_mailbox_id>/<item_id>.msg, re-adds the message to
the account with zmmailbox addMessage, preserving folder, received date,
flags, unread state and tags, and applies an extra tag (default
"Restored-<date>") so every restored message can be found, or removed, later.
Folders are created when absent.  One zmmailbox process per account, driven
through a command file, so the JVM starts once per account not per message.
Writes <LIST>.result.tsv with the new item id (or the error) for every row.
"""
import collections
import re
import datetime
import os
import subprocess
import sys
import tempfile

FLAG_LETTERS = [(1, "s"), (4, "r"), (8, "w"), (32, "f"), (64, "d"), (1024, "!"), (2048, "?")]
ZROOT = "/opt/zextras" if os.path.isdir("/opt/zextras") else "/opt/zimbra"


def opt(name, default=None):
    for x in sys.argv[1:]:
        if x.startswith(name + "="):
            return x.split("=", 1)[1]
    return default


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    lst, blobdir = args[0], args[1]
    tag = opt("--tag", "Restored-" + datetime.date.today().isoformat())
    limit = int(opt("--limit", "0"))
    only = set(opt("--only", "").split(",")) - {""}
    dry = "--dry-run" in sys.argv
    rows = collections.defaultdict(list)
    with open(lst, encoding="utf-8") as f:
        hdr = f.readline().rstrip("\n").split("\t")
        for line in f:
            r = dict(zip(hdr, line.rstrip("\n").split("\t")))
            if only and r["account"] not in only:
                continue
            rows[r["account"]].append(r)
    res = open(lst + ".result.tsv", "a", encoding="utf-8")
    total = ok = 0
    for acct, items in sorted(rows.items()):
        items.sort(key=lambda r: int(r["date"]))
        if limit:
            items = items[:max(0, limit - total)]
            if not items:
                break
        present = [r for r in items if os.path.isfile(os.path.join(blobdir, r["src_mailbox_id"], r["item_id"] + ".msg"))]
        folders = sorted({r["folder"] for r in present}, key=lambda p: p.count("/"))
        # tags must exist before addMessage references them; createTag on an
        # existing tag reports mail.ALREADY_EXISTS, which is harmless
        src_tags = sorted({t for r in present for t in r["tags"].split("\\0") if t})
        cmds = [f"createTag {q(t)}" for t in [tag] + src_tags]
        for p in folders:
            cmds.append(f"createFolder {q('/' + p)}")
        for r in present:
            fl = "".join(l for bit, l in FLAG_LETTERS if int(r["flags"]) & bit) + ("u" if int(r["unread"]) else "")
            # mail_item.tag_names is NUL-delimited; the mysql dump writes NUL as the two characters "\0"
            tags = [t for t in r["tags"].split("\\0") if t] + [tag]
            blob = os.path.join(blobdir, r["src_mailbox_id"], r["item_id"] + ".msg")
            cmds.append(f"addMessage -d {int(r['date']) * 1000}" + (f" -F {fl}" if fl else "")
                        + f" -T {q(','.join(tags))} --noValidation {q('/' + r['folder'])} {blob}")
        print(f"{acct}: {len(present)} of {len(items)} blobs present, {len(folders)} folders", flush=True)
        total += len(items)
        if dry or not present:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".zmm", delete=False, encoding="utf-8") as cf:
            cf.write("\n".join(cmds) + "\n")
        p = subprocess.run([f"{ZROOT}/bin/zmmailbox", "-z", "-m", acct, "-f", cf.name],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        os.unlink(cf.name)
        # zmmailbox -f echoes its prompt before each command and answers addMessage
        # with "<new id> (<file>)"; createFolder on an existing folder reports
        # mail.ALREADY_EXISTS, which is expected and harmless.
        got = dict((m.group(2), m.group(1)) for m in re.finditer(r"(\d+) \((\S+?)\)", p.stdout))
        for r in present:
            blob = os.path.join(blobdir, r["src_mailbox_id"], r["item_id"] + ".msg")
            new = got.get(blob, "")
            res.write("\t".join([acct, r["src_mailbox_id"], r["item_id"], r["digest"], new]) + "\n")
            ok += bool(new)
        res.flush()
        errs = [l for l in (p.stdout + p.stderr).splitlines() if "ERROR" in l and "ALREADY_EXISTS" not in l]
        if errs or p.returncode or len(got) < len(present):
            print(f"   rc={p.returncode} imported={len(got)}/{len(present)} errors={len(errs)}: "
                  + " | ".join(errs[:3])[:400], flush=True)
    print(f"done: {ok} imported of {total} listed; results in {lst}.result.tsv")


if __name__ == "__main__":
    main()
