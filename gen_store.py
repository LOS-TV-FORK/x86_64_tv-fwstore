#!/usr/bin/env python3
"""gen_store.py — builder for the LOS-TV-FORK/x86_64_tv-fwstore repository.

Layout of the repo after a run:
    manifest.json                      typed manifest consumed by FirmwareTool
    files/<family>/<basename>.<tag>    raw firmware payloads (plain .bin,
                                       exactly as in linux-firmware)

Every referenced linux-firmware release tag contributes one Variant entry
per file. TAG references: a tag (e.g. 20250913), a branch (master), or a
full parent-repo URL. Files are downloaded from
https://raw.githubusercontent.com/torvalds/linux-firmware/<ref>/<path>.

Usage:
    gen_store.py --out DIR TAG [TAG ...]
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request


# (firmware family dir, file basename in linux-firmware, device hints)
# devices: list of USB VID:PID hints (BT dongles; will grow after field tests)
# drivers: driver-name wildcards for scanning convenience
FILES = [
    ("rtw88", "rtw8703b_fw.bin", [], {}),
    ("rtw88", "rtw8723d_fw.bin", [], {"drivers": ["rtw_8723du"]}),
    ("rtw88", "rtw8812a_fw.bin", [], {"drivers": ["rtw_8812au"]}),
    ("rtw88", "rtw8814a_fw.bin", [], {"drivers": ["rtw_8814au"]}),
    ("rtw88", "rtw8821c_fw.bin",
     [("usb", "0bda", "c811"), ("usb", "0bda", "c81a"), ("usb", "0bda", "c821")],
     {"drivers": ["rtw_8821cu"]}),
    ("rtw88", "rtw8822b_fw.bin", [], {"drivers": ["rtw_8822bu", "rtw_8822be"]}),
    ("rtw88", "rtw8822c_fw.bin", [], {"drivers": ["rtw_8822cu", "rtw_8822ce"]}),
    ("rtw89", "rtw8851b_fw.bin", [], {"drivers": ["rtw_8851bu"]}),
    ("rtw89", "rtw8852a_fw.bin", [], {"drivers": ["rtw_8852au", "rtw_8852ae"]}),
    ("rtw89", "rtw8852b_fw.bin", [], {"drivers": ["rtw_8852bu", "rtw_8852be"]}),
    ("rtw89", "rtw8852c_fw.bin", [], {"drivers": ["rtw_8852cu", "rtw_8852ce"]}),
    ("rtl_bt", "rtl8723b_fw.bin", [], {}),
    ("rtl_bt", "rtl8761b_fw.bin", [], {}),
    ("rtl_bt", "rtl8761bu_fw.bin", [], {}),
    ("rtl_bt", "rtl8821a_fw.bin", [], {}),
    ("rtl_bt", "rtl8821c_fw.bin", [], {}),
    ("rtl_bt", "rtl8822b_fw.bin", [], {}),
    ("rtl_bt", "rtl8822cu_fw.bin", [], {}),
    ("rtl_bt", "rtl8822cs_fw.bin", [], {}),
    ("rtl_bt", "rtl8852bu_fw.bin", [], {}),
]

LINUX_FW_PATHS = {
    # blobs live at the repo ROOT (AOSP copies them to /vendor/firmware)
    "rtw88": lambda b: "rtw88/" + b,
    "rtw89": lambda b: "rtw89/" + b,
    "rtl_bt": lambda b: "rtl_bt/" + b,
}


def fetch(url, out):
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return  # idempotent cache inside the repo worktree
    req = urllib.request.Request(url, headers={"User-Agent": "los-fwstore/1"})
    with urllib.request.urlopen(req, timeout=30) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f)


def main():
    args = sys.argv[1:]
    if "--out" in args and len(args) >= 3:
        out = args[args.index("--out") + 1]
        args = args[args.index("--out") + 2:]
    else:
        out = os.path.dirname(os.path.abspath(__file__))
    if not args:
        sys.exit("usage: gen_store.py [--out DIR] TAG [TAG ...]")

    files_out = []
    for family, base, devices, hints in FILES:
        fw_path = LINUX_FW_PATHS[family](base)
        variants = []
        for tag in args:
            # kernel.org cgit plain blob endpoint: no LFS, stable, tag-pinned
            url = ("https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
                   "linux-firmware.git/plain/%s?h=%s" % (fw_path, tag))
            dst = os.path.join(out, "files", family, "%s.%s" % (base, tag))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                fetch(url, dst)
            except Exception as e:
                print("WARN: %s @%s: %s" % (fw_path, tag, e))
                continue
            sha = hashlib.sha256(open(dst, "rb").read()).hexdigest()
            variants.append({
                "tag": tag,
                "suffix": "",
                "sha256": sha,
                "size": os.path.getsize(dst),
                "url": "https://raw.githubusercontent.com/LOS-TV-FORK/x86_64_tv-fwstore/main/files/%s/%s.%s" % (family, base, tag),
            })
        if not variants:
            continue
        entry = {
            "path": "%s/%s" % (family, base),
            "devices": [{"type": t, "vid": v, "pid": p} for t, v, p in devices],
            "variants": variants,
        }
        for k, v in hints.items():
            entry[k] = v
        files_out.append(entry)

    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump({"version": 1, "files": files_out}, f, indent=2)
        f.write("\n")
    print("manifest: %d files" % len(files_out))


if __name__ == "__main__":
    main()
