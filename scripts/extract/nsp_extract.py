#!/usr/bin/env python3
"""Switch NSP decryption, ExeFS extraction and RomFS inventory.

Implements the container formats directly so that the project does not depend
on hactool behaviour that differs between builds:

  PFS0 (NSP)  ->  NCA header (AES-XTS)  ->  section bodies (AES-CTR)
  ->  ExeFS (PFS0) files and a RomFS file inventory.

The RomFS inventory is produced by streaming the encrypted section and
decrypting only the metadata blocks, so a 9 GB title never has to be written
to disk in full.
"""
import argparse
import json
import os
import struct
import sys
from pathlib import Path

try:
    from Crypto.Cipher import AES
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # pragma: no cover
    print("BLOCKED_TOOLCHAIN: pycryptodome and cryptography are required", file=sys.stderr)
    sys.exit(2)

NCA_HEADER_SIZE = 0xC00
SECTOR = 0x200


def load_keyset(path: Path):
    keys = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            name, value = [x.strip() for x in line.split("=", 1)]
            keys[name] = value
    return keys


def xts_decrypt(key: bytes, blob: bytes) -> bytes:
    """NCA headers use AES-XTS with the sector index as the tweak."""
    out = bytearray()
    for index in range(len(blob) // SECTOR):
        tweak = index.to_bytes(16, "big")
        decryptor = Cipher(algorithms.AES(key), modes.XTS(tweak)).decryptor()
        chunk = blob[index * SECTOR:(index + 1) * SECTOR]
        out += decryptor.update(chunk) + decryptor.finalize()
    return bytes(out)


def ctr_decrypt(key: bytes, nonce: bytes, counter: int, blob: bytes) -> bytes:
    """NCA bodies use AES-CTR with a 16 byte IV: nonce || sector counter."""
    iv = bytearray(16)
    for i in range(8):
        iv[i] = nonce[7 - i]
    shift = counter
    for i in range(8):
        iv[15 - i] = shift & 0xFF
        shift >>= 8
    decryptor = Cipher(algorithms.AES(key), modes.CTR(bytes(iv))).decryptor()
    return decryptor.update(blob) + decryptor.finalize()


class Nsp:
    def __init__(self, path: Path, keys: dict):
        self.path = path
        self.keys = keys
        self.size = os.path.getsize(path)
        self.f = path.open("rb")
        self.entries = self._read_pfs0_index()
        self.tik = self._read_tik()
        self.nca_name, self.nca_offset, self.nca_size = self._find_program_nca()
        self.header = self._decrypt_nca_header()
        self.sections = [self._section_info(i) for i in range(4)]

    # ---------- PFS0 ----------
    def _read_pfs0_index(self):
        magic = self.f.read(4)
        if magic != b"PFS0":
            raise ValueError(f"not a PFS0 container: {magic!r}")
        file_count, string_table_size = struct.unpack("<II", self.f.read(8))
        self.f.read(4)  # reserved; the entry table starts at 0x10
        raw = []
        for _ in range(file_count):
            offset, size = struct.unpack("<QQ", self.f.read(16))
            str_offset, str_size = struct.unpack("<II", self.f.read(8))
            raw.append((offset, size, str_offset, str_size))
        table = self.f.read(string_table_size)
        self.data_start = self.f.tell()
        entries = []
        for offset, size, str_offset, str_size in raw:
            end = table.find(b"\x00", str_offset)
            if end < 0:
                end = str_offset + str_size
            name = table[str_offset:end].decode("utf-8", "replace")
            entries.append({"name": name, "offset": self.data_start + offset, "size": size})
        return entries

    def _find_program_nca(self):
        candidates = [e for e in self.entries if e["name"].endswith(".nca")]
        if not candidates:
            raise ValueError("no .nca inside the NSP")
        best = max(candidates, key=lambda e: e["size"])
        return best["name"], best["offset"], best["size"]

    def _read_tik(self):
        entry = next((e for e in self.entries if e["name"].endswith(".tik")), None)
        if entry is None:
            raise ValueError("no .tik inside the NSP")
        self.f.seek(entry["offset"])
        return self.f.read(entry["size"])

    def read(self, offset: int, size: int) -> bytes:
        self.f.seek(offset)
        return self.f.read(size)

    # ---------- ticket ----------
    def titlekey_candidates(self):
        """Yield (kek_name, titlekey_bytes) for every titlekek in the keyset."""
        enc_titlekey = self.tik[0x180:0x190]
        for name, kek_hex in sorted(self.keys.items()):
            if not name.startswith("titlekek_"):
                continue
            kek = bytes.fromhex(kek_hex)
            yield name, AES.new(kek, AES.MODE_ECB).decrypt(enc_titlekey)

    def rights_id(self) -> str:
        return self.tik[0x2A0:0x2B0].hex()

    # ---------- NCA ----------
    def _decrypt_nca_header(self):
        candidates = []
        if "header_key" in self.keys:
            candidates.append(("header_key", bytes.fromhex(self.keys["header_key"])))
        for index in range(16):
            name = f"key_area_key_application_{index:02x}"
            if name in self.keys:
                candidates.append((name, bytes.fromhex(self.keys[name])))
        blob = self.read(self.nca_offset, NCA_HEADER_SIZE)
        for name, key in candidates:
            plain = xts_decrypt(key, blob)
            if plain[0x200:0x204] in (b"NCA2", b"NCA3"):
                self.header_key_name = name
                return plain
        raise ValueError("no key decrypts the NCA header (NCA2/NCA3 magic not found)")

    def _section_info(self, index: int):
        base = 0x400 + index * 0x200
        fs_header = self.header[base:base + 0x200]
        media_start = struct.unpack("<I", self.header[0x240 + index * 0x10:0x244 + index * 0x10])[0]
        media_end = struct.unpack("<I", self.header[0x244 + index * 0x10:0x248 + index * 0x10])[0]
        nonce = fs_header[0x140:0x148]
        encryption_type = struct.unpack("<I", fs_header[0x04:0x08])[0]
        key_area = struct.unpack("<I", fs_header[0x144:0x148])[0]
        return {"index": index, "media_start": media_start, "media_end": media_end,
                "media_offset": media_start * SECTOR, "nonce": nonce,
                "encryption_type": encryption_type, "key_area": key_area}

    def body_key(self, section, titlekey: bytes) -> bytes:
        """Encryption type 3 and 260 (AES-CTR for rights-id titles) use the title key."""
        if section["encryption_type"] in (3, 260):
            return titlekey
        name = f"key_area_key_application_{section['key_area']:02x}"
        if name not in self.keys:
            raise ValueError(f"missing {name} for section {section['index']}")
        return bytes.fromhex(self.keys[name])

    def section_bytes(self, section, titlekey: bytes, offset_in_section: int, size: int) -> bytes:
        key = self.body_key(section, titlekey)
        base = self.nca_offset + section["media_offset"] + offset_in_section
        blob = self.read(base, size)
        counter = (section["media_offset"] + offset_in_section) >> 4
        return ctr_decrypt(key, section["nonce"], counter, blob)

    # ---------- ExeFS ----------
    @staticmethod
    def _pfs0_entries(image: bytes):
        """Parse a PFS0 image; returns (entries, data_start) or None when invalid."""
        if len(image) < 0x10 or image[:4] != b"PFS0":
            return None
        file_count, string_table_size = struct.unpack("<II", image[4:12])
        if file_count == 0 or file_count > 256:
            return None
        table_end = 0x10 + file_count * 0x18 + string_table_size
        if table_end > len(image):
            return None
        raw = []
        for i in range(file_count):
            offset, size = struct.unpack("<QQ", image[0x10 + i * 0x18:0x20 + i * 0x18])
            str_offset, str_size = struct.unpack("<II", image[0x20 + i * 0x18:0x28 + i * 0x18])
            raw.append((offset, size, str_offset, str_size))
        table = image[0x10 + file_count * 0x18:table_end]
        entries = []
        for offset, size, str_offset, str_size in raw:
            end = table.find(b"\x00", str_offset)
            if end < 0:
                end = str_offset + str_size
            name = table[str_offset:end].decode("utf-8", "replace")
            if not name:
                return None
            if table_end + offset + size > len(image):
                return None
            entries.append((name, offset, size))
        return entries, table_end

    def exefs_image(self, titlekey: bytes) -> bytes:
        """Return the ExeFS file-level PFS0 image.

        The section starts with padding and may contain byte sequences that
        look like a PFS0 header, so every candidate is parsed and only a
        structurally valid image is accepted. The ExeFS root holds a single
        nested PFS0, which is unwrapped here.
        """
        section = self.sections[0]
        section_size = max(0, (section["media_end"] - section["media_start"])) * SECTOR
        if section_size <= 0 or section_size > 0x8000000:
            section_size = 0x100000
        window = self.section_bytes(section, titlekey, 0, section_size)
        index = 0
        while True:
            found = window.find(b"PFS0", index)
            if found < 0:
                raise ValueError("no valid PFS0 image in section 0")
            index = found + 1
            parsed = self._pfs0_entries(window[found:])
            if parsed is None:
                continue
            entries, data_start = parsed
            blobs = [window[found + data_start + off:found + data_start + off + size]
                     for _, off, size in entries]
            if len(blobs) == 1 and blobs[0][:4] == b"PFS0":
                return blobs[0]
            if any(blob[:4] in (b"NSO0", b"MOD0", b"ERSO", b"NSO2") for blob in blobs):
                return window[found:]
        return window

    def extract_exefs(self, titlekey: bytes, out_dir: Path):
        image = self.exefs_image(titlekey)
        parsed = self._pfs0_entries(image)
        if parsed is None:
            raise ValueError("ExeFS image is not a valid PFS0")
        entries, data_start = parsed
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for name, offset, size in entries:
            blob = image[data_start + offset:data_start + offset + size]
            (out_dir / name).write_bytes(blob)
            written.append({"name": name, "size": size})
        return written

    # ---------- RomFS ----------
    def romfs_base(self, titlekey: bytes) -> int:
        """Locate the RomFS level 5 image inside section 1.

        Standard NCAs carry an IVFC header whose level 5 offset is at 0x48.
        Other hash types do not, so the section is scanned for a plausible
        RomFS header instead of failing outright.
        """
        section = self.sections[1]
        ivfc = self.section_bytes(section, titlekey, 0, 0x100)
        if ivfc[:4] == b"IVFC":
            level5_offset = struct.unpack("<Q", ivfc[0x48:0x50])[0]
            candidate = section["media_offset"] + level5_offset
            if self._romfs_header_plausible(candidate, titlekey):
                return candidate
        window = self.section_bytes(section, titlekey, 0, 0x4000000)
        index = 0
        while True:
            found = window.find(struct.pack("<Q", 0x50), index)
            if found < 0:
                break
            index = found + 1
            candidate = section["media_offset"] + found
            if self._romfs_header_plausible(candidate, titlekey):
                return candidate
        raise ValueError("no RomFS header found in section 1")

    def _romfs_header_plausible(self, base_in_nca: int, titlekey: bytes) -> bool:
        section = self.sections[1]
        try:
            header = self.section_bytes(section, titlekey, base_in_nca - section["media_offset"], 0x50)
        except Exception:
            return False
        if len(header) < 0x50:
            return False
        (header_size, dir_hash_ofs, dir_hash_sz, dir_meta_ofs, dir_meta_sz,
         file_hash_ofs, file_hash_sz, file_meta_ofs, file_meta_sz,
         data_ofs) = struct.unpack("<QQQQQQQQQQ", header)
        if header_size != 0x50:
            return False
        section_size = max(0, (section["media_end"] - section["media_start"])) * SECTOR
        limit = section_size + 0x100000
        if not (0 < dir_meta_sz < 0x10000000 and 0 < file_meta_sz < 0x10000000):
            return False
        if dir_meta_ofs + dir_meta_sz > limit or file_meta_ofs + file_meta_sz > limit:
            return False
        return dir_meta_ofs < file_meta_ofs

    def romfs_inventory(self, titlekey: bytes):
        section = self.sections[1]
        base = self.romfs_base(titlekey)

        def read_at(offset, size):
            start = offset - base
            return self.section_bytes(section, titlekey, start, size)

        header = read_at(base, 0x50)
        (header_size, dir_hash_ofs, dir_hash_sz, dir_meta_ofs, dir_meta_sz,
         file_hash_ofs, file_hash_sz, file_meta_ofs, file_meta_sz,
         data_ofs) = struct.unpack("<QQQQQQQQQQ", header)

        dir_meta = read_at(base + dir_meta_ofs, dir_meta_sz)
        file_meta = read_at(base + file_meta_ofs, file_meta_sz)

        dirs = {}
        cur = 0
        while cur < len(dir_meta):
            p_dir, s_dir, c_dir, c_file, h_sib, name_len = struct.unpack("<IIIIII", dir_meta[cur:cur + 24])
            name = dir_meta[cur + 24:cur + 24 + name_len].decode("utf-8", "replace")
            dirs[cur] = {"name": name, "p_dir": p_dir}
            cur += (24 + name_len + 3) & ~3

        def dir_path(offset):
            parts = []
            current = offset
            while current != 0 and current in dirs:
                parts.append(dirs[current]["name"])
                current = dirs[current]["p_dir"]
            return "/".join(reversed(parts))

        files = []
        cur = 0
        while cur < len(file_meta):
            p_dir, s_file, d_ofs, d_sz, h_sib, name_len = struct.unpack("<IIQQII", file_meta[cur:cur + 32])
            name = file_meta[cur + 32:cur + 32 + name_len].decode("utf-8", "replace")
            parent = dir_path(p_dir) if p_dir in dirs else ""
            files.append({"path": f"{parent}/{name}" if parent else name,
                          "size": d_sz, "data_offset": data_ofs + d_ofs})
            cur += (32 + name_len + 3) & ~3
        return files, {"data_ofs": data_ofs, "dir_meta_size": dir_meta_sz,
                       "file_meta_size": file_meta_sz}


def main():
    parser = argparse.ArgumentParser(description="Decrypt a Switch NSP and inventory it")
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    local_root = (Path(__file__).resolve().parents[2] / ".local").resolve()
    if not args.out.resolve().is_relative_to(local_root):
        parser.error("--out must be inside this project's .local directory")

    keys = load_keyset(args.keys)
    nsp = Nsp(args.nsp, keys)
    print(f"[+] program NCA: {nsp.nca_name} offset={nsp.nca_offset} size={nsp.nca_size}")
    print(f"[+] NCA header key: {nsp.header_key_name}")
    print(f"[+] rights id: {nsp.rights_id()}")
    for section in nsp.sections:
        print(f"    section{section['index']}: media_start={section['media_start']} "
              f"encryption_type={section['encryption_type']} key_area={section['key_area']} "
              f"media_end={section['media_end']}")

    chosen = None
    for kek_name, titlekey in nsp.titlekey_candidates():
        try:
            written = nsp.extract_exefs(titlekey, args.out)
        except ValueError:
            continue
        nso_files = []
        for item in written:
            path = args.out / item["name"]
            if path.exists() and path.stat().st_size > 4:
                with path.open("rb") as handle:
                    if handle.read(4) in (b"NSO0", b"MOD0", b"ERSO"):
                        nso_files.append(item["name"])
        if nso_files:
            print(f"[SUCCESS] titlekek {kek_name} selected")
            print(f"[+] ExeFS files: {', '.join(w['name'] for w in written)}")
            print(f"[+] NSO modules: {', '.join(nso_files)}")
            chosen = (kek_name, titlekey, written)
            break
    if chosen is None:
        print("FAILED: no titlekek produced a valid NSO0 main.nso", file=sys.stderr)
        return 1

    kek_name, titlekey, written = chosen
    key_path = args.out.parent / "titlekey.json"
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as key_file:
        json.dump({"nsp": str(args.nsp), "kek": kek_name, "titlekey": titlekey.hex(),
                   "rights_id": nsp.rights_id(), "nca_header_key": nsp.header_key_name},
                  key_file, indent=2)

    report = {"nsp": str(args.nsp), "nca": nsp.nca_name, "nca_size": nsp.nca_size,
              "titlekek": kek_name,
              "rights_id": nsp.rights_id(), "exefs": written}
    try:
        files, romfs_info = nsp.romfs_inventory(titlekey)
        total = sum(f["size"] for f in files)
        report["romfs"] = {"file_count": len(files), "total_bytes": total, "files": files}
        print(f"[+] RomFS: {len(files)} files, {total} bytes")
        for item in sorted(files, key=lambda x: -x["size"])[:15]:
            print(f"    {item['size']:>12}  {item['path']}")
    except Exception as exc:  # inventory is best effort, extraction already succeeded
        report["romfs_error"] = repr(exc)
        print(f"[!] RomFS inventory failed: {exc!r}")

    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
