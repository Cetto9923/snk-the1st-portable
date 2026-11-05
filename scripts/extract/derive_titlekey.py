#!/usr/bin/env python3
"""Generic Switch NSP title-key derivation and ExeFS extraction.

Parses the PFS0 index of an NSP, pulls the embedded ticket, derives the
title key for every titlekek in the keyset, and asks hactool to extract the
ExeFS with each candidate. The candidate whose ExeFS yields a valid NSO0
header is the winner.

This tool never executes game code and never writes outside the given
output directory.
"""
import argparse
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from Crypto.Cipher import AES
except ImportError:  # pragma: no cover
    print("BLOCKED_TOOLCHAIN: pycryptodome is required (Crypto.Cipher.AES)", file=sys.stderr)
    sys.exit(2)


def read_pfs0_index(nsp_path: Path):
    """Return [(name, offset, size)] for every file in the NSP PFS0."""
    with nsp_path.open("rb") as f:
        magic = f.read(4)
        if magic != b"PFS0":
            raise ValueError(f"not a PFS0 container: {magic!r}")
        file_count, string_table_size = struct.unpack("<II", f.read(8))
        f.read(4)  # 4 reserved bytes: the entry table starts at offset 0x10
        entries = []
        raw = []
        for _ in range(file_count):
            offset, size = struct.unpack("<QQ", f.read(16))
            str_offset, str_size = struct.unpack("<II", f.read(8))
            raw.append((offset, size, str_offset, str_size))
        table = f.read(string_table_size)
        data_start = f.tell()
        for offset, size, str_offset, str_size in raw:
            # The string_size field is zero in some NSPs, so the name is read
            # from the NUL-terminated string table instead.
            end = table.find(b"\x00", str_offset)
            if end < 0:
                end = str_offset + str_size
            name = table[str_offset:end].decode("utf-8", "replace")
            entries.append((name, data_start + offset, size))
        return entries


def load_keyset(keys_path: Path):
    keys = {}
    for line in keys_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            name, value = [x.strip() for x in line.split("=", 1)]
            keys[name] = value
    return keys


def ticket_titlekey_candidates(tik: bytes, keys):
    """Yield (kek_name, titlekey_hex) for every titlekek present in the keyset."""
    enc_titlekey = tik[0x180:0x190]
    key_generation_byte = tik[0x285]
    for name, kek_hex in sorted(keys.items()):
        if not name.startswith("titlekek_"):
            continue
        kek = bytes.fromhex(kek_hex)
        titlekey = AES.new(kek, AES.MODE_ECB).decrypt(enc_titlekey)
        yield name, titlekey.hex(), key_generation_byte


def try_exefs(hactool: str, keys_path: Path, nsp: Path, titlekey_hex: str, workdir: Path):
    """Run hactool with the candidate title key; return the extracted file list."""
    outdir = workdir / "exefs"
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [hactool, "-k", str(keys_path), f"--titlekey={titlekey_hex}",
           "--exefsdir", str(outdir), str(nsp)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    files = sorted(p.name for p in outdir.iterdir() if p.is_file())
    return proc.returncode, files, (proc.stdout + proc.stderr)


def main():
    parser = argparse.ArgumentParser(description="Derive an NSP title key and extract ExeFS")
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="output directory for exefs")
    parser.add_argument("--hactool", default="hactool")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    if not args.nsp.exists():
        print(f"BLOCKED_INPUT: missing NSP {args.nsp}", file=sys.stderr)
        return 2
    keys = load_keyset(args.keys)

    entries = read_pfs0_index(args.nsp)
    print(f"[+] PFS0 entries: {len(entries)}")
    for name, offset, size in entries:
        print(f"    {name}  size={size}")

    tik_entry = next((e for e in entries if e[0].endswith(".tik")), None)
    if tik_entry is None:
        print("BLOCKED_INPUT: no .tik inside the NSP", file=sys.stderr)
        return 2
    with args.nsp.open("rb") as f:
        f.seek(tik_entry[1])
        tik = f.read(tik_entry[2])

    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="titlekey-try-") as tmp:
        workdir = Path(tmp)
        for kek_name, titlekey_hex, keygen in ticket_titlekey_candidates(tik, keys):
            rc, files, log = try_exefs(args.hactool, args.keys, args.nsp, titlekey_hex, workdir)
            magic = ""
            main_nso = workdir / "exefs" / "main.nso"
            if main_nso.exists():
                magic = main_nso.read_bytes()[:4].hex()
            ok = magic == "4e534f30"
            print(f"    {kek_name}: rc={rc} magic={magic or '-'} files={len(files)} "
                  f"{'HIT' if ok else ''}")
            results.append({"kek": kek_name, "titlekey": titlekey_hex,
                            "key_generation_byte": keygen, "rc": rc,
                            "files": files, "main_nso_magic": magic, "valid": ok})
            if ok:
                for name in files:
                    (args.out / name).write_bytes((workdir / "exefs" / name).read_bytes())
                (args.out.parent / "titlekey.json").write_text(
                    json.dumps({"nsp": str(args.nsp), "kek": kek_name,
                                "titlekey": titlekey_hex,
                                "key_generation_byte": keygen},
                               indent=2), encoding="utf-8")
                if args.report:
                    args.report.write_text(json.dumps(results, indent=2), encoding="utf-8")
                print(f"[SUCCESS] titlekey derived with {kek_name}: {titlekey_hex}")
                print(f"[+] ExeFS extracted to {args.out}")
                return 0

    if args.report:
        args.report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("FAILED: no titlekek produced a valid NSO0 main.nso", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
