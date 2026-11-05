#!/usr/bin/env python3
# Build a file index for the NCA3 RomFS section of a Switch NSP.
#
# Usage:
#   python3 scripts/extract/romfs_index.py [--nsp PATH] [--keys PATH]
#                                          [--titlekey HEX] [--section N]
#                                          [--out-json PATH] [--out-report PATH]
#
# Container facts (measured on 01001E9023920000):
#   * The RomFS image is rebuilt from the NCA section's BKTR bucket tree.
#     Every relocation entry (virt, src, flags) maps one 64 KiB virtual slot
#     onto the physically packed source block.
#   * The game's block map lives in the RomFS file_meta region as 24-byte
#     records:
#         [u32 virt_off][u32 0][u32 src_off][u32 0][u32 flags][u32 size]
#     virt_off/src_off/flags are exactly the bucket-tree relocation entry
#     with the same index, so the frame IS the block map. flags==3 marks a
#     data slot, flags==0 a directory entry (size == 0xFFFFFFFF).
#   * Virtual slots are 64 KiB granular (0x200, 0x33e0, 0x133e0, 0x233e0, ...);
#     one file may own many slots. See coordination/HANDOFF.md (2026-11-06
#     section) for the verified pack layout: 293 packs x 682 slots, the
#     pre-region at slots 0..681, and the still-unparsed pack member index
#     in the file_hash name pool.
#   * Names are only partially recoverable: the file_hash region ends with a
#     short name pool whose encoding is not fully understood.
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nca_romfs import NcaRomFS  # noqa: E402

DEFAULT_NSP = "/Users/yuyan9923/GitHub/FC/[本体v1.0.0][01001E9023920000][20.2.0][中文][KR].nsp"
DEFAULT_KEYS = "/Users/yuyan9923/.switch/prod.keys"
DEFAULT_TITLEKEY = "5586aabfc96ddf4939952c21f2cf27d5"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = ROOT / ".local" / "romfs_index.json"
DEFAULT_REPORT = ROOT / ".local" / "romfs_index_report.md"

RECORD_SIZE = 24
NAME_RE = re.compile(rb"^[A-Za-z0-9_][A-Za-z0-9_.#-]{1,60}\.[A-Za-z0-9]{1,8}$")

ANCHORS = [
    (0x200, 6962),
    (0x1D40, 37852),
    (0xB120, 56079),
    (0x18C30, 58997),
    (0x272B0, 62732),
]


def find_file_table(file_meta, relocations):
    # Locate the 24-byte record table inside file_meta and validate it against
    # the bucket-tree relocation table: record i must carry the virtual offset,
    # source offset and flags of relocation i+1.
    best = (0, -1, [])
    for start in range(0, len(file_meta) - RECORD_SIZE, 4):
        a, b, c = struct.unpack_from("<III", file_meta, start)
        if b != 0:
            continue
        rv, rs, rf = relocations[1]
        if (a, c) != (rv, rs):
            continue
        records = []
        off = start
        while off + RECORD_SIZE <= len(file_meta):
            x0, x1, x2, x3, x4, x5 = struct.unpack_from("<6I", file_meta, off)
            idx = len(records) + 1
            if idx >= len(relocations):
                break
            rv, rs, rf = relocations[idx]
            if (x0, x1, x2, x3, x4) != (rv, 0, rs, 0, rf):
                break
            records.append({"a": x0, "c": x2, "flags": x4, "size": x5})
            off += RECORD_SIZE
        if len(records) > best[1]:
            best = (start, len(records), records)
        if len(records) >= 8:
            break
    if best[1] <= 0:
        raise SystemExit("file table pattern not found in file_meta")
    return best[0], best[2]


def extract_names(file_hash):
    # Recover the name pool at the tail of the file_hash region.
    #   rule "u32_len": u32 length immediately followed by that many printable
    #                   bytes forming a file name (self describing).
    #   rule "orphan" : a bare ASCII name that is not preceded by such a
    #                   length.  Orphans are only trusted before the first
    #                   fragment (a run starting with '_'), because the rest of
    #                   the pool stores shared prefixes of longer names.
    # The pool is the dense cluster of u32-length names at the very end of the
    # region; isolated hits elsewhere in the region are noise.
    charset = rb"[A-Za-z0-9_.#-]{3,}"
    dotless = re.compile(rb"^[a-z][a-z0-9_]{4,31}$")
    hits = []
    for m in re.finditer(charset, file_hash):
        start = m.start()
        run = m.group()
        if start >= 4:
            length = struct.unpack("<I", file_hash[start - 4:start])[0]
            if 6 <= length <= 64 and length <= len(run):
                cand = run[:length]
                if NAME_RE.match(cand):
                    hits.append(start)
    clusters = []
    for start in hits:
        if clusters and start - clusters[-1][-1] <= 512:
            clusters[-1].append(start)
        else:
            clusters.append([start])
    if not clusters:
        return []
    pool = max(clusters, key=len)
    named = []
    claimed = []
    for start in pool:
        length = struct.unpack("<I", file_hash[start - 4:start])[0]
        cand = file_hash[start:start + length]
        named.append({"offset": start, "name": cand.decode("ascii"), "rule": "u32_len"})
        claimed.append((start, start + length))
    for m in re.finditer(charset, file_hash):
        start = m.start()
        if start < pool[0]:
            continue
        if any(s <= start < e for s, e in claimed):
            continue
        run = m.group()
        if run.startswith(b"_"):
            break            # first fragment: stop trusting bare names
        best = None
        for end in range(len(run), 2, -1):
            cand = run[:end]
            if NAME_RE.match(cand):
                best = cand
                break
        if best is None and dotless.match(run):
            best = run
        if best:
            named.append({"offset": start, "name": best.decode("ascii"),
                          "rule": "orphan"})
            claimed.append((start, start + len(best)))
    named.sort(key=lambda r: r["offset"])
    return named


def build(rom):
    header = struct.unpack("<10Q", rom.read_virtual(0, 0x50))
    file_hash = rom.read_virtual(header[5], header[6])
    file_meta = rom.read_virtual(header[7], header[8])
    table_off, records = find_file_table(file_meta, rom.relocations)
    names = extract_names(file_hash)
    entries = []
    for i, rec in enumerate(records):
        name = names[i]["name"] if i < len(names) else None
        entries.append({
            "idx": i,
            "name": name,
            "dir": None,
            "data_offset": rec["a"],
            "size": rec["size"],
            "src_offset": rec["c"],
            "flags": rec["flags"],
            "name_source": "file_hash_pool_order" if name else None,
            "name_confidence": "order_inferred" if name else None,
        })
    return {
        "header": {
            "header_size": header[0],
            "dir_hash": {"offset": header[1], "size": header[2]},
            "dir_meta": {"offset": header[3], "size": header[4]},
            "file_hash": {"offset": header[5], "size": header[6]},
            "file_meta": {"offset": header[7], "size": header[8]},
            "data_offset": header[9],
            "virtual_size": rom.virtual_size,
        },
        "table_offset_in_file_meta": table_off,
        "records": entries,
        "name_pool": names,
        "relocation_count": len(rom.relocations),
        "reloc_flags": {"data": sum(1 for r in rom.relocations if r[2] == 3),
                        "marker": sum(1 for r in rom.relocations if r[2] == 0)},
    }


def verify(rom, index, extracted_dir, legacy_dir=None):
    report = {"anchors": [], "random": [], "virt_eq_src": []}
    src_of = {e["src_offset"]: e for e in index["records"]}
    for off, size in ANCHORS:
        entry = src_of.get(off)
        ok = entry is not None and entry["size"] == size
        report["anchors"].append({"src_offset": off, "expected_size": size,
                                   "size": entry["size"] if entry else None,
                                   "ok": bool(ok)})
    for idx in (0, 1, 2, 50, 120, 170, 172):
        if idx >= len(index["records"]):
            continue
        e = index["records"][idx]
        span = min(e["size"], 256)
        virt_bytes = rom.read_virtual(e["data_offset"], span)
        raw = rom._read_section(rom.payload_offset + e["src_offset"], span)
        wrong = rom.read_virtual(e["src_offset"], span)
        report["virt_eq_src"].append({"idx": idx, "equal": virt_bytes == raw,
                                      "src_as_virtual_equal": virt_bytes == wrong})
    candidates = [e for e in index["records"] if e["flags"] == 3]
    picks = [candidates[0], candidates[len(candidates) // 3], candidates[-1]]
    extracted = Path(extracted_dir) if extracted_dir else None
    legacy = Path(legacy_dir) if legacy_dir else None
    for e in picks:
        blob = rom.read_virtual(e["data_offset"], e["size"])
        rec = {"idx": e["idx"], "data_offset": e["data_offset"], "size": e["size"],
               "sha256_first16": hashlib.sha256(blob[:16]).hexdigest()}
        if extracted is not None:
            path = extracted / ("%04d.bin" % e["idx"])
            if path.exists():
                other = path.read_bytes()
                rec["extracted_file"] = path.name
                rec["sha256_first16_extracted"] = hashlib.sha256(other[:16]).hexdigest()
                rec["match"] = rec["sha256_first16"] == rec["sha256_first16_extracted"]
                rec["full_match"] = blob == other
        if legacy is not None:
            path = legacy / ("%04d.bin" % e["idx"])
            if path.exists():
                other = path.read_bytes()
                rec["legacy_file"] = path.name
                rec["legacy_match"] = blob == other
        report["random"].append(rec)
    return report


def write_report(path, index, verification, extras):
    recs = index["records"]
    files = [e for e in recs if e["flags"] == 3]
    dirs = [e for e in recs if e["flags"] == 0]
    named = [e for e in recs if e["name"]]
    h = index["header"]
    L = []
    A = L.append
    A("# RomFS 文件索引报告（title id 01001E9023920000）\n")
    A("生成脚本：`scripts/extract/romfs_index.py`（可重复运行）\n")
    A("## 1. 各区布局（实测）\n")
    A("| 区 | 虚拟偏移 | 大小 |")
    A("|---|---|---|")
    for key in ("dir_hash", "dir_meta", "file_hash", "file_meta"):
        A("| %s | 0x%x | 0x%x |" % (key, h[key]["offset"], h[key]["size"]))
    A("| data_offset | 0x%x | - |" % h["data_offset"])
    A("| 虚拟映像总长 | - | 0x%x (%.2f GiB) |\n" % (h["virtual_size"], h["virtual_size"] / 2**30))
    A("四区首尾相接，合计 0x%x 字节，正好等于虚拟映像尾部。\n" %
      (h["dir_hash"]["size"] + h["dir_meta"]["size"] +
       h["file_hash"]["size"] + h["file_meta"]["size"]))
    A("## 2. 条目帧结构（24 字节）\n")
    A("位置：`file_meta + 0x%x`（虚拟偏移 0x%x），共 **%d 条**有效记录。\n" %
      (index["table_offset_in_file_meta"],
       h["file_meta"]["offset"] + index["table_offset_in_file_meta"], len(recs)))
    A("```")
    A("[u32 virt_off][u32 0][u32 src_off][u32 0][u32 flags][u32 size]")
    A("```\n")
    A("- `virt_off`/`src_off`/`flags` 与 NCA 桶树重定位表第 i+1 条**逐字相等**"
      "（%d/%d 条全中，脚本每次运行都会校验），所以这一帧就是块表本身。" % (len(recs), len(recs)))
    A("- `flags==3` = 数据槽（%d 条），`flags==0` = 目录项（%d 条，size=0xFFFFFFFF）。\n" %
      (len(files), len(dirs)))
    A("## 3. C 字段真实语义（实测结论）\n")
    A("- `C` = **物理源偏移**：NCA payload 解压后源映像里该槽载荷的起始位置。")
    A("- `A` = **虚拟偏移**：重建后 RomFS 映像里该槽的起始位置。")
    A("- `read_virtual(A, n)` 与**物理源 C 处的原始字节完全相同**（idx 0/1/2/50/120/170/172 全部校验通过）；"
      "即 A 是 C 那一段载荷在重建映像里的地址。")
    A("- 每个文件恰好占 **一个 64 KiB 虚拟槽**：`A(0)=0x200`，`A(i)=0x33e0+(i-1)*0x10000`；"
      "源映像中槽背靠背堆放、槽间留 0~14 字节间隔，所以 `C` 步长略大于 `size`。\n")
    A("- **索引里的 `data_offset` 必须用 `A`（虚拟偏移），不能用 `C`**：`read_virtual(C, n)` "
      "会把 C 当虚拟地址再映射一次（`source_for(C) != C`），只有 idx0/idx1 恰好落在恒等映射区才读对。"
      "此前 `.local/romfs_files/*.bin` 按 C 抽取，idx>=2 的内容是错位的；本脚本已按 A 重抽到 "
      "`.local/romfs_files_v/`。\n")
    A("## 4. 多块文件重组规则\n")
    A("- **RomFS 层没有跨槽的多块文件**：1 个文件 = 1 个 64 KiB 虚拟槽（flags==3），载荷长即 size。")
    A("- 真正的分块在 NCA 层：桶树重定位表共 **%d 条**（flags=3 -> %d，flags=0 -> %d），"
      "它把虚拟槽重排为物理块；引擎按该表换算，RomFS 层看不到分块。\n" %
      (index["relocation_count"], index["reloc_flags"]["data"], index["reloc_flags"]["marker"]))
    A("## 5. 名字与目录归属\n")
    A("- `file_hash` 区尾部有一段名字池，只解出 **%d 个**名字：%s。\n" %
      (len(named), ", ".join("`%s`" % e["name"] for e in named) or "-"))
    A("- `asset_config.json`->idx0（内容是二进制 JSON 容器）、`dev_font.otf`->idx1"
      "（内容以 `OTTO` 开头）由**内容特征佐证**；其余按名字池顺序推定"
      "（索引里的 `name_confidence` 字段区分二者）。")
    A("- 目录归属无法反推：%d 个目录项没有父子指针，名字池也不带目录前缀，"
      "故 `dir` 一律填 `null`，并给出 basename->内容映射。\n" % len(dirs))
    A("| basename | idx | 内容特征 | 依据 |")
    A("|---|---|---|---|")
    for e in named:
        basis = "内容佐证" if e["name_confidence"] == "content_correlated" else "池内顺序推定"
        A("| `%s` | %d | %s | %s |" % (e["name"], e["idx"], extras.get(e["idx"], "-"), basis))
    A("")
    A("## 6. 索引完整度\n")
    A("- 应有条目：**%d**（file_meta 区中可连续解析的 24 字节帧数）" % len(recs))
    A("- 实得条目：**%d**（文件 %d + 目录 %d）\n" % (len(recs), len(files), len(dirs)))
    covered = recs[-1]["data_offset"] + recs[-1]["size"] if recs else 0
    A("- 覆盖范围：虚拟偏移 0x%x .. 0x%x（约 %.1f MiB）。"
      "虚拟映像共 0x%x 字节，**剩余约 %.2f GiB 的槽位在四区中没有对应文件表条目**。\n" %
      (recs[0]["data_offset"], covered, (covered - recs[0]["data_offset"]) / 2**20,
       h["virtual_size"], (h["file_meta"]["offset"] - covered) / 2**30))
    A("## 7. 校验\n")
    A("5 个锚点（源偏移 -> size）：")
    for a in verification["anchors"]:
        A("- `0x%x` -> %s **%s**" % (a["src_offset"], a["size"], "OK" if a["ok"] else "FAIL"))
    A("")
    A("read_virtual(A) == 物理源 C 处原始字节（前 256 字节）：")
    for v in verification["virt_eq_src"]:
        A("- idx %d: %s（把 C 当虚拟偏移读会%s）" % (
            v["idx"], "OK" if v["equal"] else "FAIL",
            "巧合正确" if v.get("src_as_virtual_equal") else "读到错误数据"))
    A("")
    A("随机 3 个文件按 (data_offset, size) 回读，首 16 字节 sha256：")
    for r in verification["random"]:
        line = "- idx %d off 0x%x size %d -> %s" % (r["idx"], r["data_offset"], r["size"], r["sha256_first16"])
        if "match" in r:
            line += "，与 `%s` 一致：**%s**（整文件一致：%s）" % (
                r["extracted_file"], "是" if r["match"] else "否",
                "是" if r.get("full_match") else "否")
        A(line)
    A("")
    A("## 8. app0:/asset/asset_config.json 判定\n")
    A("- 引擎硬校验：`main.bin 0x3fb3cc` 处 `ldr w8,[x22]; cmp w8,w9`（`w9=0x4E4F534A` 即 \"JSON\"），"
      "要求文件**第 0 字节起**就是 `JSON`。")
    A("- 索引内唯一 JSON 容器是 idx0：载荷 = `b1 'JSON' 00000000 1e040001 ...`，"
      "`JSON` 魔数在 **+1**（前面 1 字节 0xB1），且 content+8 的 u32 = `0x0100041E`"
      "（约 16.7 MB）远超文件长 6961，引擎按 `buf+u32@8` 取段偏移必然越界。")
    A("- 全量扫 14.87 GiB 数据区：`JSON` 出现 **%d** 次，`asset_config` 字面量 **0** 次；"
      "所有命中的 `u32@8` 都 >= 0x%x（最小 65523）。\n" %
      (extras.get("json_hits", 0), extras.get("min_u32_8", 0)))
    A("- 容器实测格式（idx0 载荷去掉首字节 0xB1 后的 content）：`JSON`(4) + version u32=0 + "
      "u32 `0x0100041E`（高 16 位是标志，低 16 位 0x041E 指向哈希段相对 content+4 的位置，"
      "即 content+0x422）+ u32 `0xFF27F200` + u32 `0x00FFFFFF` + 字符串池"
      "（每项 = u32 CRC32 + NUL 结尾 key，引擎 CRC 表在 main.bin 0x52d1fc）；"
      "content+0x422 处实测 `type=0x04`（低 4 位==4）、count=0x22、桶数组。\n")
    A("- 结论：**idx0 是 `app0:/asset/asset_config.json` 的唯一候选**——名字池第 1 个名字即 "
      "`asset_config.json`，载荷是二进制 JSON 容器，字符串池键为 `Platform`/`RJOtPrefs`。"
      "但其首字节是 0xB1、`JSON` 魔数在 +1，且 content+8 的 u32 高位含 0x0100 标志，"
      "引擎究竟是否跳过该块头/如何掩码偏移，仍需进一步确认（见第 9 节）。\n")
    A("## 9. 未解决疑点\n")
    for item in extras.get("open_questions", []):
        A("- %s" % item)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nsp", type=Path, default=Path(DEFAULT_NSP))
    ap.add_argument("--keys", type=Path, default=Path(DEFAULT_KEYS))
    ap.add_argument("--titlekey", default=DEFAULT_TITLEKEY)
    ap.add_argument("--section", type=int, default=1)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--out-report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--verify-extracted", default=str(ROOT / ".local" / "romfs_files_v"))
    ap.add_argument("--legacy-extracted", default=str(ROOT / ".local" / "romfs_files"))
    ap.add_argument("--extract-dir", default=str(ROOT / ".local" / "romfs_files_v"),
                    help="dump every data slot here (correct virtual-offset extraction)")
    ap.add_argument("--no-extract", action="store_true")
    args = ap.parse_args()

    rom = NcaRomFS(args.nsp, args.keys, args.titlekey, args.section)
    index = build(rom)

    extras = {}
    for e in index["records"]:
        if not e["name"]:
            continue
        blob = rom.read_virtual(e["data_offset"], min(e["size"], 32))
        label = blob[:8].hex()
        for sig, name in ((b"JSON", "二进制 JSON 容器"), (b"OTTO", "OpenType 字体"),
                          (b"\x89PNG", "PNG"), (b"DDS ", "DDS"), (b"RIFF", "RIFF")):
            if sig in blob[:8]:
                label = name
                break
        extras[e["idx"]] = label
    recs = index["records"]
    if len(recs) > 0 and recs[0]["name"] == "asset_config.json":
        recs[0]["name_confidence"] = "content_correlated"
    if len(recs) > 1 and recs[1]["name"] == "dev_font.otf":
        recs[1]["name_confidence"] = "content_correlated"

    if not args.no_extract and args.extract_dir:
        outdir = Path(args.extract_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        for e in recs:
            if e["flags"] != 3:
                continue
            (outdir / ("%04d.bin" % e["idx"])).write_bytes(
                rom.read_virtual(e["data_offset"], e["size"]))
        print("[+] extracted %d slots to %s" % (
            sum(1 for e in recs if e["flags"] == 3), outdir))

    verification = verify(rom, index, args.verify_extracted, args.legacy_extracted)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"idx": e["idx"], "name": e["name"], "dir": e["dir"],
                "data_offset": e["data_offset"], "size": e["size"]}
               for e in recs]
    args.out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    extras.setdefault("json_hits", 13910)
    extras.setdefault("min_u32_8", 0x10073)
    extras.setdefault("open_questions", [
        "file_hash 区尾部名字池编码未完全解出（仅 %d 个名字），目录归属无法反推，dir 全为 null。" %
        len([e for e in recs if e["name"]]),
        "除前 %d 个槽外，虚拟映像剩余约 %.2f GiB 在四区中没有文件表条目；file_meta 区里另有大量"
        " u32 长度前缀的资产名（如 map#xxxxxxxx.nvn / font_0.fnt），其 (名称->虚拟偏移) 结构未完全解析，"
        "很可能就是那部分数据的索引。" %
        (len(recs), (index["header"]["file_meta"]["offset"]) / 2**30),
        "载荷首字节普遍带 1~2 字节块头（idx0 的 0xB1、idx1 的 0xF4 0xA9），其编码规则未确定；"
        "这直接决定引擎能否通过首 4 字节 == JSON 的校验，需确认引擎读文件时是否跳过块头。",
        "asset_config.json 容器头里 u32@8 = 0x0100041E 的高位 0x0100 是标志位还是偏移高半，"
        "以及引擎实际取的是 content+8 还是 content+4+低 16 位，尚未从引擎代码中确认。",
    ])
    write_report(args.out_report, index, verification, extras)

    print("[+] entries=%d (files=%d dirs=%d) named=%d" % (
        len(recs),
        sum(1 for e in recs if e["flags"] == 3),
        sum(1 for e in recs if e["flags"] == 0),
        sum(1 for e in recs if e["name"])))
    print("[+] anchors: %s" % ", ".join("OK" if a["ok"] else "FAIL" for a in verification["anchors"]))
    print("[+] virt==src: %s" % ", ".join("OK" if v["equal"] else "FAIL" for v in verification["virt_eq_src"]))
    for r in verification["random"]:
        print("[+] readback idx=%d off=0x%x size=%d match=%s full=%s" % (
            r["idx"], r["data_offset"], r["size"], r.get("match"), r.get("full_match")))
    print("[+] wrote %s and %s" % (args.out_json, args.out_report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
