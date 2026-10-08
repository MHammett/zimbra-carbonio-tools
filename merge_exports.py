#!/usr/bin/env python3
"""Merge several restore TSVs (from diff_inventory.py --export) so each
missing message is restored once, from the first source listed.

    python merge_exports.py OUT_PREFIX SRC1.tsv SRC2.tsv ...

Writes OUT_PREFIX.<n>.tsv per input, containing only the rows whose
(account, digest) was not already claimed by an earlier input, so each
output can be fetched from and imported for its own source server.
"""
import os
import sys


def main():
    prefix, inputs = sys.argv[1], sys.argv[2:]
    seen = set()
    for n, path in enumerate(inputs, 1):
        out = f"{prefix}.{n}.tsv"
        kept = dropped = 0
        with open(path, encoding="utf-8") as f, open(out, "w", encoding="utf-8", newline="") as o:
            hdr = f.readline()
            o.write(hdr)
            cols = hdr.rstrip("\n").split("\t")
            ia, idg = cols.index("account"), cols.index("digest")
            for line in f:
                r = line.rstrip("\n").split("\t")
                key = (r[ia], r[idg])
                if key in seen:
                    dropped += 1
                    continue
                seen.add(key)
                o.write(line)
                kept += 1
        print(f"{os.path.basename(path)} -> {out}: kept {kept:,}, dropped {dropped:,} already covered by an earlier source")


if __name__ == "__main__":
    main()
