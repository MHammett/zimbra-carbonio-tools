import sys, gzip, csv, collections, datetime, os
csv.field_size_limit(1 << 30)
d = sys.argv[1]
boxes = {int(r[0]): r[3].lower() for r in csv.reader(open(os.path.join(d, "mailboxes.tsv"), encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}
bymonth = collections.Counter(); first = {}
with gzip.open(os.path.join(d, "mail_item.tsv.gz"), "rt", encoding="utf-8", errors="replace", newline="") as f:
    for r in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(r) < 17 or r[2] != "5": continue
        e = boxes.get(int(r[0]), "?"); dom = e.split("@")[-1]
        cd = int(r[16]) if r[16] else 0
        if not cd: continue
        m = datetime.datetime.fromtimestamp(cd, datetime.timezone.utc).strftime("%Y-%m")
        bymonth[(dom, m)] += 1
        if e not in first or cd < first[e]: first[e] = cd
print(f"== {d}: messages by domain and change-month (import spikes), top 15")
for (dom, m), c in sorted(bymonth.items(), key=lambda x: -x[1])[:15]: print(f"  {c:9,}  {dom:22} {m}")
fd = collections.Counter(datetime.datetime.fromtimestamp(v, datetime.timezone.utc).strftime("%Y-%m-%d") for v in first.values())
print("  earliest change_date per mailbox, by day:", ", ".join(f"{k}:{v}" for k, v in sorted(fd.items())[:12]), "...")
