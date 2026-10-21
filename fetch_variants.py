#!/usr/bin/env python3
"""fetch_variants.py — download selected files per tag, build manifest.json v2.

Parallel, cache-friendly (fetch cache lives inside the repo worktree at
files/<vendor-path>.<tag>), tolerant to 404 for older tags, listens to
per-family tag caps: everything under intel/iwlwifi|intel/iboost gets
TAGS_INTEL newest snapshots only.
"""
import concurrent.futures as fut
import hashlib, json, os, re, shutil, sys, time, urllib.request, urllib.error

HOME = "/tmp/opencode/vadec/fwstore"
SEL = os.path.join(HOME, "selection.json")
BASE = ("https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
        "linux-firmware.git/plain/{src}?h={tag}")
OUT_URL = ("https://raw.githubusercontent.com/LOS-TV-FORK/x86_64_tv-fwstore/main/"
           "files/{vend}.{tag}")

TAGS = ["20261019", "20260916", "20260810", "20260622",
        "20260410", "20260221", "20260519", "20251125"]
TAGS_INTEL = 3

UA = {"User-Agent": "los-fwstore/1"}
entries = json.load(open(SEL))

def intel_limited(row):
    return row["src"].startswith(("intel/iwlwifi/", "intel/ibt-", "intel/ibt2"))

def fetch_task(row, tag):
    src, vend = row["src"], row["vendor"]
    dst = os.path.join(HOME, "files", vend + "." + tag)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return ("cache", vend, tag)
    url = BASE.format(src=src, tag=tag)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r, open(dst, "wb") as f:
                shutil.copyfileobj(r, f)
            return ("ok", vend, tag)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if os.path.exists(dst):
                    os.remove(dst)
                return ("missing", vend, tag)
        except Exception:
            pass
        time.sleep(3 + attempt * 2)
    return ("fail", vend, tag)

def main():
    tasks = []
    seen = set()
    for row in entries:
        tags = TAGS[:TAGS_INTEL] if intel_limited(row) else TAGS
        for tag in tags:
            key = (row["src"], tag)
            if key in seen:
                continue
            seen.add(key)
            tasks.append((row, tag))
    results = []
    with fut.ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(fetch_task, r, t) for (r, t) in tasks]
        for i, f in enumerate(futs):
            results.append(f.result())
            print("done %d/%d row=%s" % (i + 1, len(tasks), results[-1][1]), flush=True)
    from collections import Counter
    print(Counter(s for s, _, _ in results))
    fails = [(v, t) for (s, v, t) in results if s == "fail"]
    print("hard fails:", len(fails))

    rows = []
    for row in entries:
        tags = TAGS[:TAGS_INTEL] if intel_limited(row) else TAGS
        variants = []
        for tag in tags:
            dst = os.path.join(HOME, "files", row["vendor"] + "." + tag)
            if not (os.path.exists(dst) and os.path.getsize(dst) > 0):
                print("WARN skip %s @%s" % (row["vendor"], tag))
                continue
            data = open(dst, "rb").read()
            variants.append({
                "tag": tag, "suffix": "",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": os.path.getsize(dst),
                "url": OUT_URL.format(vend=row["vendor"], tag=tag),
            })
        if not variants:
            print("WARN file without variants, dropped:", row["vendor"])
            continue
        rows.append({
            "path": row["vendor"],
            "devices": row.get("devices", []),
            "role": row["role"],
            "label": row["label"],
            "aliases": row["aliases"],
            "drivers": row["drivers"],
            "vendors": row["vendors"],
            "variants": variants,
        })
    with open(os.path.join(HOME, "manifest.json"), "w") as f:
        json.dump({"version": 2, "files": rows}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print("manifest files:", len(rows))
    # prune stale payloads not referenced
    keep = set(row["path"] + "." + v["tag"] for row in rows for v in row["variants"])
    removed = 0
    for root, _, files in os.walk(os.path.join(HOME, "files")):
        for n in files:
            p = os.path.relpath(os.path.join(root, n), os.path.join(HOME, "files"))
            if p not in keep and not p.endswith(".tmp"):
                os.remove(os.path.join(root, n))
                removed += 1
    print("pruned", removed)

if __name__ == "__main__":
    main()
