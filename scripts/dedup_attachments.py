#!/usr/bin/env python3
"""Dedup atașamente prin hardlink. DRY-RUN by default.

Sigur: nu șterge niciun conținut — înlocuiește o cale duplicat cu un hardlink
către un fișier IDENTIC păstrat (byte-cu-byte, verificat prin SHA-256), doar în
același filesystem. Swap atomic (link tmp -> rename peste original), deci nu există
moment în care fișierul lipsește. Fișierele de atașament sunt write-once, deci
hardlink-ul e sigur.

  python3 dedup_attachments.py <dir>            # dry-run (raportează cât s-ar recupera)
  python3 dedup_attachments.py <dir> --apply    # aplică hardlink-urile
  optional: --min-size N (default 1024 bytes — ignoră fișierele mai mici)
"""
import os, sys, stat, hashlib, argparse, time
from collections import defaultdict


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--apply", action="store_true", help="aplică hardlink (default: dry-run)")
    ap.add_argument("--min-size", type=int, default=1024)
    args = ap.parse_args()
    t0 = time.time()

    by_size = defaultdict(list)
    nfiles = 0
    for base, _dirs, files in os.walk(args.root):
        for fn in files:
            p = os.path.join(base, fn)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size < args.min_size:
                continue
            by_size[(st.st_size, st.st_dev)].append((p, st.st_ino))
            nfiles += 1

    dup_sets = dup_files = reclaim = linked = errors = already = hashed = 0
    for (size, _dev), items in by_size.items():
        if len(items) < 2:
            continue
        by_hash = defaultdict(list)
        for p, ino in items:
            try:
                by_hash[sha256(p)].append((p, ino))
                hashed += 1
            except OSError:
                errors += 1
        for _hsh, group in by_hash.items():
            if len(group) < 2:
                continue
            dup_sets += 1
            keep_path, keep_ino = group[0]
            for p, ino in group[1:]:
                if ino == keep_ino:
                    already += 1
                    continue
                dup_files += 1
                reclaim += size
                if args.apply:
                    tmp = p + ".dedup_tmp"
                    try:
                        os.link(keep_path, tmp)
                        os.replace(tmp, p)
                        linked += 1
                    except OSError:
                        errors += 1
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass

    print("fișiere scanate:           %d" % nfiles)
    print("fișiere hash-uite:         %d" % hashed)
    print("seturi duplicate:          %d" % dup_sets)
    print("fișiere duplicate:         %d" % dup_files)
    print("deja hardlinkate:          %d" % already)
    print("spațiu recuperabil:        %.2f GB" % (reclaim / 1073741824))
    print("erori (skip):              %d" % errors)
    print("durată:                    %.0f s" % (time.time() - t0))
    if args.apply:
        print(">>> APLICAT: %d fișiere hardlinkate" % linked)
    else:
        print(">>> DRY-RUN — nimic modificat. Rulează cu --apply pentru hardlink.")


if __name__ == "__main__":
    main()
