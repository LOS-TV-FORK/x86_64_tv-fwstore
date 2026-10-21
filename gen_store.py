#!/usr/bin/env python3
"""gen_store.py v2 — builder for the LOS-TV-FORK/x86_64_tv-fwstore repo.

Layout: manifest.json + files/<fw-dir>/<file>.<tag>, where <fw-dir> mirrors
the linux-firmware layout 1:1 — FirmwareTool bind-mounts over
/vendor/firmware/<fw-dir>/<file>, so the mirror MUST match that layout
(repo-root blobs like ibt-11-5.sfi stay at the store root).

Coverage targets the x86 world from ~2010 onward:
  Intel_WIFI (iwlwifi ucode), Intel BT (ibt*.sfi), Realtek rtw88/rtw89 +
  rtl_bt + rtlwifi (USB), Atheros ath10k/BT (rampatch/nvm) + ath9k_htc +
  carl9170 + ath3k, Qualcomm ath11k/ath12k, Broadcom (brcm), MediaTek.

Per-module tag caps keep the repo sane: Intel ucode gets TAGS_INTEL newest
snapshots (identical contents dedupe in git by blob), everything else uses
all requested tags.

Usage:  gen_store.py [--out DIR] TAG [TAG ...]
(manifest schema is additive: old FirmwareTool keeps working on v1 fields,
new fields role/vendors/drivers/label/aliases are optional in code.)
"""
import hashlib, json, os, re, shutil, sys, time, urllib.request

BASE_URL = ("https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
            "linux-firmware.git/plain/{path}?h={tag}")
TREE_URL = ("https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
            "linux-firmware.git/tree/{path}?h={tag}&ofs={ofs}")
OUT_URL = ("https://raw.githubusercontent.com/LOS-TV-FORK/x86_64_tv-fwstore/main/"
           "files/{fam}/{name}.{tag}")

TAGS_INTEL = 3

ATH10K_SOCS = ("QCA6174", "QCA9377", "QCA9887", "QCA9888", "QCA988X", "QCA9984", "QCA99X0", "WCN3990")
ATH11K_SOCS = ("QCA6390", "WCN6855", "WCN6750")
ATH12K_SOCS = ("WCN7850",)

STATIC_FAMILIES = {
    "rtw88": [
        "rtw8703b_fw.bin", "rtw8723d_fw.bin", "rtw8812a_fw.bin", "rtw8814a_fw.bin",
        "rtw8821c_fw.bin", "rtw8822b_fw.bin", "rtw8822c_fw.bin",
    ],
    "rtw89": [
        "rtw8851b_fw.bin", "rtw8852a_fw.bin", "rtw8852b_fw.bin", "rtw8852c_fw.bin",
    ],
}


# ---------- static-only legacy table (kept for nicer labels/aliases) ------
LABELS = {  # basename-neutral -> human info
    "rtw8703b_fw.bin":   ("Realtek RTL8703B (USB Wi-Fi)", ["RTL8703BU"], ["rtw_8703bu"]),
    "rtw8723d_fw.bin":   ("Realtek RTL8723D (USB Wi-Fi)", ["RTL8723DU"], ["rtw_8723du"]),
    "rtw8812a_fw.bin":   ("Realtek RTL8812A (USB Wi-Fi)", ["RTL8812AU"], ["rtw_8812au"]),
    "rtw8814a_fw.bin":   ("Realtek RTL8814A (USB Wi-Fi)", ["RTL8814AU"], ["rtw_8814au"]),
    "rtw8821c_fw.bin":   ("Realtek RTL8821CU / RTL8811CU (USB Wi-Fi)", ["RTL8821CU", "RTL8811CU"], ["rtw_8821cu"]),
    "rtw8822b_fw.bin":   ("Realtek RTL8822B (USB/PCIe Wi-Fi)", ["RTL8822BU"], ["rtw_8822bu", "rtw_8822be"]),
    "rtw8822c_fw.bin":   ("Realtek RTL8822C (USB/PCIe Wi-Fi)", ["RTL8822CU"], ["rtw_8822cu", "rtw_8822ce"]),
    "rtw8851b_fw.bin":   ("Realtek RTL8851B (USB Wi-Fi)", ["RTL8851BU"], ["rtw_8851bu"]),
    "rtw8852a_fw.bin":   ("Realtek RTL8852A (USB Wi-Fi)", ["RTL8852AU"], ["rtw_8852au"]),
    "rtw8852b_fw.bin":   ("Realtek RTL8852B (USB Wi-Fi)", ["RTL8852BU"], ["rtw_8852bu"]),
    "rtw8852c_fw.bin":   ("Realtek RTL8852C (USB Wi-Fi)", ["RTL8852CU"], ["rtw_8852cu"]),
}

MODULES = [
    # ---- Intel WiFi ucode (loaded from /vendor/firmware root!) ----
    {"dir": "intel/iwlwifi", "store": "", "role": "wifi", "group": "intel-wifi",
     "filter": r"^iwlwifi-.+\.ucode$", "drivers": ["iwlwifi"], "tags": TAGS_INTEL},
    # ---- Intel Bluetooth INTEL DIR (bind path /vendor/firmware/intel/…) ----
    {"dir": "intel", "store": "intel", "role": "bt", "group": "intel-bt",
     "filter": r"^ibt-[\d\-]+(?:\.[a-z]+)?\.sfi$|^ibt-[\d\-]+(?:\.[a-z]+)?\.ddc$",
     "drivers": ["btusb"], "vendors": ["8087"], "tags": TAGS_INTEL},
    # ---- Realtek families (86/89) ----
    {"dir": "rtw88", "store": "rtw88", "role": "wifi", "group": "rtl-wifi",
     "static": STATIC_FAMILIES["rtw88"], "tags": 8},
    {"dir": "rtw89", "store": "rtw89", "role": "wifi", "group": "rtl-wifi",
     "static": STATIC_FAMILIES["rtw89"], "tags": 8},
    # ---- Realtek BT ----
    {"dir": "rtl_bt", "store": "rtl_bt", "role": "bt", "group": "rtl-bt",
     "filter": r"^rtl\w*_fw(\.\w+)?\.bin$", "drivers": ["btusb"],
     "vendors": ["0bda"], "tags": 8},
    # ---- Realtek USB dongles (rtl8xxxu et al.) ----
    {"dir": "rtlwifi", "store": "rtlwifi", "role": "wifi", "group": "rtl-usb",
     "filter": r"^rtl(\d+[a-z]*u?w?)\.bin$|^rtl\d+[a-z]*\.bin$", "drivers": ["rtl8xxxu"], "tags": 8},
    # ---- Atheros ath9k HTG / carl9170 / ath3k (repo root) — exact names ----
    {"dir": "ath9k_htc", "store": "ath9k_htc", "role": "wifi", "group": "ath9k-htc",
     "filter": r"^htc_[97][\w.]+\.fw$", "drivers": ["ath9k_htc"], "tags": 8},
    {"dir": "", "store": "", "role": "wifi", "group": "carl",
     "filter": r"^carl9170-(1|2)\.fw$", "drivers": ["carl9170"], "tags": 8},
    {"dir": "", "store": "", "role": "bt", "group": "ath3k",
     "filter": r"^ath3k-1\.fw$|^ath3k-2\.fw$", "drivers": ["btusb", "ath3k"],
     "vendors": ["0cf3"], "tags": 8},
    # ---- Qualcomm/Atheros ath10k PCIe+USB dongles (nested soc dirs) ----
    {"dir": "ath10k", "store": "ath10k", "role": "wifi", "group": "ath10k",
     "nested": True, "socs": ATH10K_SOCS, "reject": r"notice|\.txt$",
     "drivers": ["ath10k_usb"], "tags": 8},
    {"dir": "ath11k", "store": "ath11k", "role": "wifi", "group": "ath11k",
     "nested": True, "socs": ATH11K_SOCS, "reject": r"Notice|\.txt$",
     "drivers": ["ath11k_pci"], "tags": 8},
    {"dir": "ath12k", "store": "ath12k", "role": "wifi", "group": "ath12k",
     "nested": True, "socs": ATH12K_SOCS, "reject": r"Notice|\.txt$",
     "drivers": ["ath12k_pci"], "tags": 8},
    # ---- Qualcomm BT (ath3k rampatches/nvm) ----
    {"dir": "qca", "store": "qca", "role": "bt", "group": "qca-bt",
     "filter": r"^(rampatch_usb_|nvm_usb_|rampatch_00|nvm_00)[\w.\-]+$",
     "drivers": ["btusb", "qca_recv"], "vendors": ["0cf3"], "tags": 8},
    # ---- Broadcom (wifi bins + BT hcd) ----
    {"dir": "brcm", "store": "brcm", "role": "auto", "group": "brcm",
     "filter": r"^[a-zA-z0-9].*\.(bin|hcd|txt)$", "drivers": ["brcmfmac", "btusb"],
     "vendors": ["0a5c", "0bb4"], "tags": 8},
    # ---- MediaTek (USB dongles + BT for 792x laptops, nested dirs) ----
    {"dir": "mediatek", "store": "mediatek", "role": "auto", "group": "mtk",
     "filter": r"^(mt7601u|mt7610[eu]|mt7650|mt7662|mt7663|mt7615_|mt7668pr2h"
               r"|BT_RAM_CODE_MT7|WIFI_(RAM_CODE|MT7902|MT7922|MT7961))[\w.\-]*\.bin$",
     "dirs": ["mediatek/mt7925", "mediatek/mt7927"],
     "drivers": ["mt7601u", "mt7610u", "mt76x0e", "mt7662u", "mt7921u", "mt7922u", "btusb"],
     "vendors": ["0e8d"], "tags": 8},
]


def fetch(url, out, tries=6):
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return
    req = urllib.request.Request(url, headers={"User-Agent": "los-fwstore/1"})
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(out, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except urllib.error.HTTPError as e:
            raise e  # let caller distinguish 404 for real
        except Exception as e:
            last = e
            sys.stderr.write("retry %d/%d %s\n" % (attempt + 1, tries, out))
            time.sleep(5)
    raise last


# ---------- cgit tree enumeration with pagination ----------
def list_dir(path, tag):
    path = path.rstrip("/")
    files, subs, ofs = set(), {}, 0
    while True:
        req = urllib.request.Request(
            TREE_URL.format(path=path if path else "", tag=tag, ofs=ofs),
            headers={"User-Agent": "los-fwstore/1"})
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        row = re.findall(
            r"class='ls-(\w+)(?: \w+)?' href=[^>]*?tree/" + re.escape(path)
            + (r"/" if path else r"") + r"([^/?]+)\?h=", html)
        newly = row
        if not newly and ofs == 0:
            return [], {}
        for cls, n in newly:
            if cls == "blob":
                if path:
                    files.add(path + "/" + n)
                else:
                    files.add(n)
            else:
                subs[n] = (path + "/" + n if path else n)
        m = re.search(r"ofs=(\d+)'[^>]*?>next", html)
        if not m:
            break
        nxt = int(m.group(1))
        if nxt <= ofs:
            break
        ofs = nxt
        time.sleep(0.7)
    return sorted(files), dict(**{k: v for k, v in subs.items()})


def list_nested(dirpath, tag, socs, depth=3):
    """Full recursive listing truncated to given top-level soc groups."""
    files, _ = list_dir(dirpath, tag)
    results = []
    for socdir, subs in files[-1:]:
        pass
    return results
