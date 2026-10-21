#!/usr/bin/env python3
"""gen_store.py v2 — builder for LOS-TV-FORK/x86_64_tv-fwstore.

Layout: manifest.json + files/<vendor-path>/<file>.<tag>.

<vendor-path> mirrors the /vendor/firmware layout 1:1 because FirmwareTool
bind-mounts over exactly that. Upstream linux-furniture places some blobs
differently from their load path (iwlwifi now lives under intel/iwlwifi
upstream but the kernel loads it from the[root]; htc_*.fw and  ar9271.fw /
carl9170 / ath3k live at the repo root), so every module declares BOTH:
  upstream  — where the file is fetched from in the linux-firmware repo
  vendor    — where the kernel asks for it (what the store mirrors)

Coverage: the whole x86 Wi-Fi/BT zoo from ~2010 (Intel ucode + ibt BT,
Realtek rtw88/89 + rtl_bt + rtlwifi USB, Atheros ath9k_htc/carf9170/ath3k,
Qualcomm ath10k Bt rampatches, ath11k, ath12k, Broadcom brcm, MediaTek).

Per-module tag caps guard repo size (identical contents dedupe across tags
via git blobs; Intel historically churns slowly too but stays capped).

Usage:  gen_store.py [--out DIR] TAG [TAG ...]
"""
import hashlib, json, os, re, shutil, sys, time, urllib.request, urllib.error

TREES = ("https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
         "linux-firmware.git/tree/{path}?h={tag}&ofs={ofs}")
PLAIN = ("https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
         "linux-firmware.git/plain/{path}?h={tag}")
OUT_URL = ("https://raw.githubusercontent.com/LOS-TV-FORK/x86_64_tv-fwstore/main/"
           "files/{path}.{tag}")
TAGS_INTEL = 3

# ---------------------------------------------------------------- modules
# upstream   fetch location inside linux-firmware ("" = repo root)
# vendor     store path prefix (= /vendor/firmware layout, "" = root)
# selection  "static" | "filter" | "nested-socs"
M = lambda **kw: kw

MODULES = [
    M(name="intel-wifi", role="wifi",
      upstream="intel/iwlwifi", vendor="",
      sel=("filter", r"^iwlwifi-.+\.ucode$"),
      drivers=["iwlwifi"], devices=[],
      tags=TAGS_INTEL),
    M(name="intel-bt", role="bt",
      upstream="intel", vendor="intel",
      sel=("filter", r"^ibt-[\d\-]+(?:incrementall)?\.(sfi|ddc)$"),
      drivers=["btusb"], vendors=["8087"], devices=[],
      tags=TAGS_INTEL),
    M(name="rtl-wifi-89", role="wifi",
      upstream="rtw88+rtw89", vendor="",
      sel=("rtw",),
      devices=[], tags=8),
    M(name="rtl-bt", role="bt",
      upstream="rtl_bt", vendor="rtl_bt",
      sel=("filter", r"^rtl\w*_fw\d*\.bin$"),
      drivers=["btusb"], vendors=["0bda"], devices=[],
      tags=8),
    M(name="rtl-usb", role="wifi",
      upstream="rtlwifi", vendor="rtlwifi",
      sel=("filter", r"^rtl\w+\.bin$"),
      drivers=["rtl8xxxu"], devices=[],
      tags=8),
    M(name="ath9k", role="wifi",
      upstream="", vendor="",
      sel=("exact", ["htc_9271.fw", "htc_7010.fw", "ar9271.fw"]),
      drivers=["ath9k_htc"], devices=[],
      tags=8),
    M(name="carl9170", role="wifi",
      upstream="", vendor="",
      sel=("exact", ["carl9170-1.fw", "carl9170-2.fw"]),
      drivers=["carl9170"], devices=[],
      tags=8),
    M(name="ath3k", role="bt",
      upstream="", vendor="",
      sel=("exact", ["ath3k-1.fw", "ath3k-2.fw"]),
      drivers=["btusb"], vendors=["0cf3"], devices=[],
      tags=8),
    M(name="ath10k", role="wifi",
      upstream="ath10k", vendor="ath10k",
      sel=("nested-socs", ["QCA6174", "QCA9377", "QCA9887", "QCA9888",
                          "QCA988X", "QCA9984", "QCA99X0", "WCN3990"]),
      reject=r"[Nn]otice|\.txt$",
      drivers=["ath10k_usb"], devices=[],
      tags=8),
    M(name="ath11k", role="wifi",
      upstream="ath11k", vendor="ath11k",
      sel=("nested-socs", ["QCA6390", "WCN6855", "WCN6750"]),
      reject=r"[Nn]otice|\.txt$",
      drivers=["ath11k_pci"], devices=[],
      tags=8),
    M(name="ath12k", role="wifi",
      upstream="ath12k", vendor="ath12k",
      sel=("nested-socs", ["WCN7850"]),
      reject=r"[Nn]otice|\.txt$",
      drivers=["ath12k_pci"], devices=[],
      tags=8),
    M(name="qca-bt", role="bt",
      upstream="qca", vendor="qca",
      sel=("filter", r"^(rampatch_usb_|nvm_usb_|rampatch_00|nvm_00|"
                    r"[acocrh][pmnt]+bt|wcnhp?)"),
      drivers=["btusb"], vendors=["0cf3"], devices=[],
      tags=8),
    M(name="brcm", role="auto",
      upstream="brcm", vendor="brcm",
      sel=("filter", r"^[A-Za-z].*\.(bin|hcd|txt|trx)$"),
      drivers=["brcmfmac", "btusb"], vendors=["0a5c", "0bb4"], devices=[],
      tags=8),
    M(name="mediatek", role="auto",
      upstream="mediatek", vendor="mediatek",
      sel=("filter", r"^(mt7601u|mt7610[eu]|mt7650|mt766[23]|mt7615_|mt7622"
                    r"|BT_RAM_CODE_MT7|WIFI_(RAM_CODE_MT7|MT7902|MT7922"
                    r"|MT7961))[\w.\-]*\.bin$"),
      extra_dirs=["mediatek/mt7925", "mediatek/mt7927"],
      drivers=["mt7601u", "mt7610u", "mt76x0e", "mt7662u", "mt7921u",
               "mt7922u", "btusb"], vendors=["0e8d"], devices=[],
      tags=8),
]

RTW = {"rtw88": ("static_88",),
       "rtw89": ("static_89",)}
RTW_STATIC = {
    "rtw88": ["rtw8703b_fw.bin", "rtw8723d_fw.bin", "rtw8812a_fw.bin",
              "rtw8814a_fw.bin", "rtw8821c_fw.bin", "rtw8822b_fw.bin",
              "rtw8822c_fw.bin"],
    "rtw89": ["rtw8851b_fw.bin", "rtw8852a_fw.bin", "rtw8852b_fw.bin",
              "rtw8852c_fw.bin"],
}

# human text for Intel ucode family tokens
IW_FAM = {
    "100": "Centrino Wireless-N 100", "1000": "Centrino N 1000",
    "105": "Centrino N 105", "1030": "Centrino N 1030", "135": "Centrino N 135",
    "2000": "Centrino N 2000", "2030": "Centrino N 2030", "3160": "3160",
    "3165": "3165", "3168": "3168", "3945": "3945ABG (legacy)",
    "4965": "4965AGN (legacy)", "5000": "5000", "5150": "5150",
    "6000": "6000", "6000g2a": "6000 G2A", "6000g2b": "6000 G2B",
    "6000g2c": "6000 G2C", "6050": "6050", "6150w": "6150W",
    "6205": "6205", "6230": "6230", "6235": "6235", "6250": "6250",
    "6300": "6300", "6320": "6320", "7000": "7000", "7260": "7260",
    "7265": "7265/D", "7265D": "7265/D", "8000C": "8000C", "8260": "8260",
    "8265": "8265", "9000": "9000", "9260": "9260", "9270": "9270",
    "QuZ": "9560/9461 (QuZ-a0)", "Qu": "7350 (Qu)", "cc": "9560/9260 (cc-a0)",
    "gl": "BE20xx (gl-a0)", "ma": "AX (ma-a0)", "sc": "AX (sc-a0)",
    "so": "AX200/AX201/AX210 (so-a0)", "ty": "AX411 (ty-a0)", "bz": "BE200/BE201 (bz-a0)",
    "sun": "Wi-Fi 7 (sun-a0)",
}


# ---------------------------------------------------------------- helpers
def _get(url, dest, tries=6):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return
    req = urllib.request.Request(url, headers={"User-Agent": "los-fwstore/1"})
    last = None
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            last = e
            sys.stderr.write("retry %d/%d: %s\n" % (attempt, tries, url))
            time.sleep(4)
    raise last


def tree_list(path, tag):
    """(blobs, subdirs) on one listing page — path may be ''."""
    path = (path or "").rstrip("/")
    pat = "tree/"
    if path:
        pat += re.escape(path)
    else:
        pat += r"/"
    pat += r"([^/?]+)\?h="
    blobs, subs, ofs = [], [], 0
    while True:
        req = urllib.request.Request(TREES.format(path=path, tag=tag, ofs=ofs),
                                     headers={"User-Agent": "los-fwstore/1"})
        html = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
        rows = re.findall(r"class='ls-(\w+)(?: \w+)?' href=[^>]*?" + pat, html)
        if not rows and ofs == 0:
            return [], []
        for cls, n in rows:
            (blobs if cls == "blob" else subs).append(n)
        m = re.search(r"ofs=(\d+)[^>]*?\bnext", html)
        if not m:
            break
        nxt = int(m.group(1))
        if nxt <= ofs:
            break
        ofs = nxt
        time.sleep(0.5)
    return sorted(set(blobs)), sorted(set(subs))


def list_recursive(path, tag, depth=3, wanted_socs=None, reject=None):
    """Flatten listing below path; keep top-level socs if given."""
    files, subs = tree_list(path, tag)
    result = []
    top = ((save_soc(path, blob) not in None) if False else None)
    return result
