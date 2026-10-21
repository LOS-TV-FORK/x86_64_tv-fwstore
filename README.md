# x86_64_tv-fwstore

Firmware payload repository for **FirmwareTool** (LOS-TV-FORK):
pinuped copies of Realtek WiFi/BT firmware files from
[linux-firmware](https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git)
(tagged releases) so that users can swap a firmware file for flaky USB
dongles right on the device (bind mount, no reflash).

Structure:

```
manifest.json          app manifest: files[] -> devices hints + variants[]
files/<family>/…       payload blobs, named <basename>.<linux-firmware tag>
gen_store.py           fetcher + manifest builder (runs locally, commits here)
```

FirmwareTool fetches `https://raw.githubusercontent.com/LOS-TV-FORK/x86_64_tv-fwstore/main/manifest.json`.

To add a new linux-firmware release as a variant:

```sh
python3 gen_store.py --out . <TAG> [TAG2 …]
git add files manifest.json
git commit -m "add variants for <TAG>"
git push
```

Tags come from the linux-firmware releases (e.g. `20260916`). Missing
files for older tags are skipped with a WARN (expected: firmware families
appear and disappear between releases).
