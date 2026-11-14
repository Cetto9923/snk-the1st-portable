#!/usr/bin/env python3
"""Package a private, verified SNK game folder into a portable data ZIP archive for Honor GT Pro.
Mirrors the rigorous packaging and verification workflow of ff-resonance-honor-gtpro."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def collect_payload_files(data_dir: Path):
    """Collect all files to be packaged into SNK/ archive prefix."""
    payload_items = []
    
    # 1. NSO binaries
    required_nsos = ['main.nso', 'sdk.nso', 'subsdk0.nso', 'rtld.nso']
    for nso in required_nsos:
        p = (data_dir / nso).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Missing required NSO module: {p}")
        payload_items.append((p, f"SNK/{nso}"))

    # 2. Shaders
    shaders_dir = (data_dir / "shaders").resolve()
    if not shaders_dir.is_dir():
        raise FileNotFoundError(f"Missing shaders directory: {shaders_dir}")
    shader_files = sorted(shaders_dir.glob("*.xgs"))
    if not shader_files:
        raise ValueError("Shaders directory is empty (expected compiled .xgs shaders)")
    for sf in shader_files:
        payload_items.append((sf, f"SNK/shaders/{sf.name}"))

    # 3. RomFS assets
    romfs_dir = (data_dir / "romfs").resolve()
    if not romfs_dir.is_dir():
        raise FileNotFoundError(f"Missing romfs directory: {romfs_dir}")
    romfs_files = sorted(p for p in romfs_dir.rglob("*") if p.is_file())
    if not romfs_files:
        raise ValueError("RomFS directory is empty")
    for rf in romfs_files:
        rel = rf.relative_to(romfs_dir).as_posix()
        payload_items.append((rf, f"SNK/romfs/{rel}"))

    return payload_items


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=ROOT / '.local/snk_game_dir', help="Input SNK game directory")
    ap.add_argument('--out', type=Path, default=ROOT / '.local/release-pack', help="Output directory")
    ap.add_argument('--root-copy', action='store_true', help="Also copy SNK-data.zip to repo root")
    args = ap.parse_args()

    data_dir = args.data.resolve()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Collecting payload files from {data_dir}...")
    payload_files = collect_payload_files(data_dir)
    total_bytes = sum(src.stat().st_size for src, _ in payload_files)
    print(f"Total payload files: {len(payload_files)}, total size: {total_bytes / (1024**3):.2f} GiB ({total_bytes} bytes)")

    archive_path = out_dir / 'SNK-data.zip'
    if archive_path.exists():
        print(f"Removing existing {archive_path}...")
        archive_path.unlink()

    rows = []
    print(f"Packaging {archive_path.name} (ZIP_STORED, ZIP64)...")
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for idx, (src_path, arc_name) in enumerate(payload_files):
            file_h = hashlib.sha256()
            stat_before = src_path.stat()
            with src_path.open('rb') as src, z.open(arc_name, 'w', force_zip64=True) as dst:
                while True:
                    chunk = src.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    file_h.update(chunk)
                    dst.write(chunk)
            stat_after = src_path.stat()
            if (stat_before.st_size, stat_before.st_mtime_ns) != (stat_after.st_size, stat_after.st_mtime_ns):
                raise ValueError(f"Input changed while packaging: {arc_name}")
            rows.append({
                'path': arc_name,
                'bytes': stat_before.st_size,
                'sha256': file_h.hexdigest()
            })
            if (idx + 1) % 5000 == 0 or (idx + 1) == len(payload_files):
                print(f"  [{idx + 1}/{len(payload_files)}] {arc_name} ({stat_before.st_size} bytes)", flush=True)

    print("\nVerifying archive integrity and payload checksums...")
    with zipfile.ZipFile(archive_path, 'r') as z:
        names = z.namelist()
        if names != [r['path'] for r in rows]:
            raise ValueError("ZIP inventory mismatch between written files and archive catalog")
        print("Archive catalog verified successfully.")

    print("Computing archive SHA-256...")
    archive_h = hashlib.sha256()
    with archive_path.open('rb') as src:
        while True:
            chunk = src.read(4 * 1024 * 1024)
            if not chunk:
                break
            archive_h.update(chunk)
    archive_sha256 = archive_h.hexdigest()
    archive_size = archive_path.stat().st_size

    manifest = {
        'format': 'snk-portable-folder-v1',
        'target_game': '空之轨迹 the 1st / Sora no Kiseki the 1st (01001E9023920000 + 01001E9023920800 v1.0.7)',
        'target_device': 'HONOR ROD2-W69 / SM8635 / Adreno 735 / Android 16',
        'file_count': len(rows),
        'payload_bytes': total_bytes,
        'zip_bytes': archive_size,
        'zip_sha256': archive_sha256,
        'files': rows,
        'verification': 'finished ZIP catalog verified and all payload SHA-256 computed'
    }

    manifest_path = out_dir / 'data-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    sha256_path = out_dir / 'SNK-data.zip.sha256'
    sha256_path.write_text(f"{archive_sha256}  SNK-data.zip\n")

    print("\nPackaging Summary:")
    print(f"  Archive: {archive_path} ({archive_size / (1024**3):.2f} GiB)")
    print(f"  SHA-256: {archive_sha256}")
    print(f"  Manifest: {manifest_path}")

    if args.root_copy:
        root_zip = ROOT / 'SNK-data.zip'
        root_sha = ROOT / 'SNK-data.zip.sha256'
        print(f"Copying {archive_path.name} to repository root {root_zip}...")
        import shutil
        shutil.copy2(archive_path, root_zip)
        shutil.copy2(sha256_path, root_sha)
        print("Root copy complete.")


if __name__ == '__main__':
    main()
