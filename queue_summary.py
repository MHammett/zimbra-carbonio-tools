import json, sys, collections, datetime
q = collections.Counter(); rdom = collections.Counter(); sdom = collections.Counter(); reason = collections.Counter()
n = 0; oldest = None; newest = None; size = 0
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: m = json.loads(line)
    except Exception: continue
    n += 1; q[m.get("queue_name")] += 1; size += m.get("message_size", 0)
    t = m.get("arrival_time")
    if t: oldest = t if oldest is None else min(oldest, t); newest = t if newest is None else max(newest, t)
    s = m.get("sender") or "<>"; sdom[s.split("@")[-1] if "@" in s else s] += 1
    for r in m.get("recipients", []):
        a = r.get("address", ""); rdom[a.split("@")[-1] if "@" in a else a] += 1
        reason[(r.get("delay_reason") or "")[:90]] += 1
f = lambda t: datetime.datetime.fromtimestamp(t).isoformat() if t else None
print(f"messages={n} size_MB={size/1e6:.0f} oldest={f(oldest)} newest={f(newest)}")
print("queues:", dict(q))
print("top recipient domains:", rdom.most_common(8))
print("top sender domains:", sdom.most_common(8))
print("top delay reasons:")
for r, c in reason.most_common(6): print(f"  {c:7d}  {r}")
