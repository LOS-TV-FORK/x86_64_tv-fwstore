#!/usr/bin/env python3
"""select_uniques.py (local-clone edition)

Same rules as the network version: per device-file pick N *unique*
(by sha256) variants walking tags newest->oldest; N=8, Intel 5.
Reads blobs from the local bare clone of upstream linux-firmware
(/tmp/opencode/vadec/fwupstream.git) — no network per file.
"""
import hashlib, json, os, subprocess

HOME = "/tmp/opencode/vadec/fwstore"
REPO = "/tmp/opencode/vadec/fwupstream.git"
SEL = json.load(open(os.path.join(HOME, "selection.json")))
TAGS = open("/tmp/opencode/vadec/tags.txt").read().split()
OUT_URL = ("https://raw.githubusercontent.com/LOS-TV-FORK/x86_64_tv-fwstore/main/"
           "files/{vend}.{tag}")

def intel_limited(row):
    return row["src"].startswith(("intel/iwlwifi/", "intel/ibt-", "intel/ibt2"))

_cache = {}

def blob(row, tag):
    """Blob bytes at <tag>:<src>, or None. Cached per (path,tag)."""
    key = (row["src"], tag)
    if key in _cache:
        return _cache[key]
    dst = os.path.join(HOME, "files", row["vendor"] + "." + tag)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        data = open(dst, "rb").read()
    else:
        p = subprocess.run(["git", "-C", REPO, "cat-file", "blob",
                            "refs/tags/%s:%s" % (tag, row["src"])],
                           capture_output=True, timeout=120)
        if p.returncode != 0:
            _cache[key] = None
            return None
        data = p.stdout
        open(dst, "wb").write(data)
    sha = hashlib.sha256(data).hexdigest()
    _cache[key] = (data, sha)
    return _cache[key]

def pick(row):
    want = 5 if intel_limited(row) else 8
    out = []
    seen = set()
    for tag in TAGS:
        if len(out) >= want:
            break
        got = blob(row, tag)
        if got is None:
            continue
        data, sha = got
        if sha in seen:
            continue
        seen.add(sha)
        out.append((tag, sha))
    return row, out

def main():
    rows = []
    keep = set()
    for i, row in enumerate(SEL):
        if i % 40 == 0:
            print("row %d/%d %s" % (i, len(SEL), row["vendor"]), flush=True)
        _, variants = pick(row)
        for tag, sha in variants:
            name = row["vendor"] + "." + tag
            keep.add(name)
        vv = []
        for tag, sha in variants:
            p = os.path.join(HOME, "files", row["vendor"] + "." + tag)
            vv.append({"tag": tag, "suffix": "", "sha256": sha,
                       "size": os.path.getsize(p),
                       "url": OUT_URL.format(vend=row["vendor"], tag=tag)})
        if not vv:
            print("DROPPED no variants:", row["vendor"], flush=True)
            continue
        rows.append({"path": row["vendor"], "devices": row.get("devices", []),
                     "role": row["role"], "label": row["label"],
                     "aliases": row["aliases"], "drivers": row["drivers"],
                     "vendors": row["vendors"], "variants": vv})
    json.dump({"version": 2, "files": rows},
              open(os.path.join(HOME, "manifest.json"), "w"),
              indent=1, ensure_ascii=False)
    root = os.path.join(HOME, "files")
    removed = 0
    for dirp, _, files in os.walk(root):
        for n in files:
            rel = os.path.relpath(os.path.join(dirp, n), root)
            if rel not in keep:
                os.remove(os.path.join(dirp, n))
                removed += 1
    print("manifest files:", len(rows), "| pruned:", removed, flush=True)

if __name__ == "__main__":
    main()
