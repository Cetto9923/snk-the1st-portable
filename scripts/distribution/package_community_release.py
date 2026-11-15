#!/usr/bin/env python3
"""Package the public application and notices, with source and APK checksums."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = ET.parse(ROOT / "src/android/app/gamewindow/AndroidManifest.xml").getroot()
    version = manifest.attrib["{http://schemas.android.com/apk/res/android}versionName"]
    destination = args.out.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    apk_name = f"snk-the1st-{version}-arm64.apk"
    shutil.copy2(args.apk, destination / apk_name)
    with zipfile.ZipFile(args.apk) as archive:
        forbidden = [name for name in archive.namelist()
                     if name.lower().endswith((".nso", ".nca", ".nsp", ".xci", ".xgs", ".keys", ".tik"))
                     or name.lower().startswith(("assets/romfs/", "assets/shaders/"))]
        if forbidden:
            raise SystemExit(f"Unexpected game inputs in APK: {forbidden}")
        licenses = [name for name in archive.namelist() if name.startswith("assets/licenses/")
                    and not name.endswith("/")]
        if not licenses:
            raise SystemExit("APK has no third-party license assets")
        for name in licenses:
            target = destination / name.removeprefix("assets/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    for name in ("安装与使用.md", "版权与免责说明.md"):
        shutil.copy2(ROOT / "docs/release" / name, destination / name)
    shutil.copy2(ROOT / "NOTICE.md", destination / "NOTICE.md")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    provenance = {
        "version": version,
        "source_repository": "https://github.com/Cetto9923/snk-the1st-portable",
        "source_commit": commit,
        "source_tree_dirty": bool(status.strip()),
        "apk": apk_name,
        "apk_sha256": sha256(args.apk),
        "game_data": "user_supplied",
        "abi": "arm64-v8a",
    }
    (destination / "release-manifest.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zip_path = destination / f"snk-the1st-{version}-community.zip"
    members = [destination / apk_name, destination / "安装与使用.md",
               destination / "版权与免责说明.md", destination / "NOTICE.md",
               destination / "release-manifest.json"]
    members.extend(path for path in (destination / "licenses").rglob("*") if path.is_file())
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(members):
            archive.write(path, path.relative_to(destination).as_posix())
    sums = members + [zip_path]
    (destination / "SHA256SUMS.txt").write_text("".join(
        f"{sha256(path)}  {path.relative_to(destination).as_posix()}\n" for path in sorted(sums)),
        encoding="utf-8")
    print(json.dumps(provenance, ensure_ascii=False, indent=2))
    print(zip_path)


if __name__ == "__main__":
    main()
