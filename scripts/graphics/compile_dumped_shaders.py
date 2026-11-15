#!/usr/bin/env python3
import sys, os, struct, json, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, SCRIPT_DIR)
import build_ffrs_xgs
import fix_spirv_capabilities as caps_tool

def compute_metadata(control):
    # NVN1 stores the actual workgroup dimensions and shared-memory bytes in
    # its control segment. The translator defaults every missing dimension
    # to one, which silently leaves most compute invocations unexecuted.
    if len(control) < 0x758:
        raise ValueError('compute control segment is shorter than 0x758 bytes')
    local = list(struct.unpack_from('<3I', control, 0x748))
    if not all(local):
        raise ValueError(f'compute control segment has a zero workgroup dimension: {local}')
    shared = struct.unpack_from('<I', control, 0x754)[0]
    return {'local': local, 'shared': (shared + 15) // 16 * 16}

def localize_1618_scratch(words):
    """Prove and localize the 44-byte per-invocation scratch used by 1618.

    This kernel declares 1024 * 44 bytes in Workgroup storage, but all 34
    accesses address its own invocation's eleven uints. The Honor GPU has
    32 KiB of shared memory. Keep its 1024 invocations and SSBO operations,
    replacing only those proven-disjoint addresses with a Private array.
    Any changed layout, escaping pointer or unproved address is an error.
    """
    parsed = list(build_ffrs_xgs.instructions(words))
    if not parsed or parsed[-1][0] + (words[parsed[-1][0]] >> 16) != len(words):
        raise ValueError('1618 scratch module has a truncated instruction')
    types = {ops[0]: (op, ops) for _, op, ops in parsed if 19 <= op <= 39}
    definitions = {ops[1]: (pos, op, ops) for pos, op, ops in parsed
                   if len(ops) >= 2 and ops[0] in types and
                   op not in (5, 6, 71, 72) and not 19 <= op <= 39}
    constants = {ops[1]: ops[2] for _, op, ops in parsed
                 if op == 43 and len(ops) == 3 and types[ops[0]][0] == 21 and
                 types[ops[0]][1][1] == 32}
    local_modes = [ops[2:] for _, op, ops in parsed if op == 16 and ops[1] == 17]
    if local_modes != [[1024, 1, 1]]:
        raise ValueError('1618 scratch requires LocalSize 1024,1,1')
    shared = [ops for _, op, ops in parsed if op == 59 and ops[2] == 4]
    if len(shared) != 1 or len(shared[0]) != 3:
        raise ValueError('1618 scratch requires one uninitialized Workgroup variable')
    variable = shared[0][1]
    pointer_op, pointer = types[shared[0][0]]
    array_op, array = types[pointer[2]]
    scalar_op, scalar = types[array[1]]
    if (pointer_op != 32 or array_op != 28 or scalar_op != 21 or
            scalar[1:] != [32, 0] or constants.get(array[2]) != 11264):
        raise ValueError('1618 scratch requires Workgroup uint[11264]')
    if any(op == 71 and ops[0] == array[0] for _, op, ops in parsed):
        raise ValueError('1618 scratch array must have no explicit layout')
    local_ids = {ops[0] for _, op, ops in parsed
                 if op == 71 and ops[1:] == [11, 27]}
    if len(local_ids) != 1:
        raise ValueError('1618 scratch requires one LocalInvocationId input')
    entry_functions = [ops[1] for _, op, ops in parsed if op == 15 and ops[0] == 5]
    if len(entry_functions) != 1:
        raise ValueError('1618 scratch requires one compute entry point')

    # Follow only single-store Function temporaries. A dominating store is
    # required even if the translated register happens to have one writer.
    stores = {}
    blocks, instruction_blocks, successors = {}, {}, {}
    current = current_function = None
    for pos, op, ops in parsed:
        if op == 54:
            current_function = ops[1]
        if op == 248 and current_function == entry_functions[0]:
            current = ops[0]
            blocks[current] = []
            successors[current] = set()
        if current is not None:
            blocks[current].append(pos)
            instruction_blocks[pos] = current
        if op == 62:
            stores.setdefault(ops[0], []).append((pos, ops[1]))
        if op == 249 and current is not None:
            successors[current].add(ops[0])
        elif op == 250 and current is not None:
            successors[current].update(ops[1:3])
        elif op == 251 and current is not None:
            successors[current].update([ops[1], *ops[3::2]])
        elif op == 56:
            current = current_function = None
    if not blocks:
        raise ValueError('1618 scratch compute entry point has no blocks')
    entry = next(iter(blocks))
    predecessors = {block: set() for block in blocks}
    for block, following in successors.items():
        for target in following:
            if target not in predecessors:
                raise ValueError('1618 scratch has an invalid branch target')
            predecessors[target].add(block)
    dominators = {block: ({entry} if block == entry else set(blocks)) for block in blocks}
    changed = True
    while changed:
        changed = False
        for block in blocks:
            if block == entry:
                continue
            parents = predecessors[block]
            common = set.intersection(*(dominators[parent] for parent in parents)) if parents else set()
            value = {block} | common
            if value != dominators[block]:
                dominators[block] = value
                changed = True

    address_temporaries = set()

    def affine(identifier, visiting=None):
        if identifier in constants:
            value = constants[identifier]
            if value >= 0x80000000:
                value -= 0x100000000
            return 0, value
        visiting = set() if visiting is None else visiting
        if identifier in visiting or identifier not in definitions:
            raise ValueError('1618 scratch address is not a proven invocation-local integer')
        visiting = visiting | {identifier}
        pos, op, ops = definitions[identifier]
        result_op, result_type = types[ops[0]]
        if result_op not in (21, 22) or result_type[1] != 32:
            raise ValueError('1618 scratch address uses a non-32-bit value')
        if op == 61:
            source = ops[2]
            source_pos, source_op, source_ops = definitions.get(source, (0, 0, []))
            if source_op == 65 and source_ops[2] in local_ids and len(source_ops) == 4:
                coordinate = constants.get(source_ops[3])
                if coordinate in (0, 1, 2):
                    return (1, 0) if coordinate == 0 else (0, 0)
            if source_op != 59 or source_ops[2] != 7 or len(stores.get(source, [])) != 1:
                raise ValueError('1618 scratch address reads a non-single-store temporary')
            address_temporaries.add(source)
            stored_pos, value = stores[source][0]
            if stored_pos not in instruction_blocks or pos not in instruction_blocks:
                raise ValueError('1618 scratch address crosses entry-point function boundaries')
            write_block, read_block = instruction_blocks[stored_pos], instruction_blocks[pos]
            if (write_block not in dominators[read_block] or
                    (write_block == read_block and stored_pos >= pos)):
                raise ValueError('1618 scratch address store does not dominate its load')
            return affine(value, visiting)
        if op in (83, 124):  # CopyObject / 32-bit Bitcast preserve address bits.
            source_type = definitions.get(ops[2], (0, 0, [0]))[2][0]
            if types.get(ops[0], (0, []))[0] not in (21, 22) or types[ops[0]][1][1] != 32:
                raise ValueError('1618 scratch address uses a non-32-bit cast')
            if source_type not in types or types[source_type][0] not in (21, 22) or types[source_type][1][1] != 32:
                raise ValueError('1618 scratch address casts a non-32-bit value')
            return affine(ops[2], visiting)
        if op not in (128, 130, 132, 194, 199):
            raise ValueError(f'1618 scratch address has unsupported opcode {op}')
        if result_op != 21:
            raise ValueError('1618 scratch address arithmetic must use 32-bit integers')
        left, right = affine(ops[2], visiting), affine(ops[3], visiting)
        if op == 128:
            result = left[0] + right[0], left[1] + right[1]
        elif op == 130:
            result = left[0] - right[0], left[1] - right[1]
        elif op == 132 and (left[0] == 0 or right[0] == 0):
            linear, constant = (left, right[1]) if right[0] == 0 else (right, left[1])
            result = linear[0] * constant, linear[1] * constant
        elif op == 194 and right[0] == 0 and 0 <= right[1] < 32:
            divisor = 1 << right[1]
            if left[0] % divisor or min(left[1], left[0] * 1023 + left[1]) < 0:
                raise ValueError('1618 scratch address shift is not an exact affine quotient')
            result = left[0] // divisor, left[1] // divisor
        elif op == 199 and right[0] == 0 and right[1] >= 0:
            low, high = sorted((left[1], left[0] * 1023 + left[1]))
            if low < 0 or high > right[1] or right[1] & (right[1] + 1):
                raise ValueError('1618 scratch address mask changes the invocation index')
            result = left
        else:
            raise ValueError('1618 scratch address is not affine in LocalInvocationId.x')
        low, high = sorted((result[1], result[0] * 1023 + result[1]))
        if low < 0 or high > 0x7fffffff:
            raise ValueError('1618 scratch address arithmetic may wrap')
        return result

    accesses = {}
    for pos, op, ops in parsed:
        if op == 65 and ops[2] == variable:
            if len(ops) != 4:
                raise ValueError('1618 scratch requires direct scalar access chains')
            coefficient, offset = affine(ops[3])
            if coefficient != 11 or not 0 <= offset < 11:
                raise ValueError('1618 scratch access leaves its invocation-local eleven uints')
            accesses[ops[1]] = offset
    if len(accesses) != 34:
        raise ValueError(f'1618 scratch requires 34 proven accesses, found {len(accesses)}')
    # Conservatively reject every other use, including pointer copies, calls,
    # atomics, whole-array loads and stores of a pointer. Literal fields are
    # excluded for declarations/debug/annotations so IDs cannot match them.
    element_pointers = accesses.keys() | address_temporaries
    declared_pointers = {variable} | address_temporaries
    for _, op, ops in parsed:
        if op in (5, 6, 8, 16, 17, 43, 71, 72) or 19 <= op <= 39:
            continue
        for pointer_id in (variable, *accesses, *address_temporaries):
            if pointer_id not in ops:
                continue
            allowed = ((op == 59 and ops[1] in declared_pointers) or
                       (op == 65 and ops[2] == variable and ops[1] in accesses) or
                       (op == 61 and ops[2] == pointer_id and pointer_id in element_pointers) or
                       (op == 62 and ops[0] == pointer_id and pointer_id in element_pointers))
            if not allowed:
                raise ValueError(f'1618 scratch pointer escapes through opcode {op}')

    bound = words[3]
    count_id, array_id, array_pointer_id, scalar_pointer_id = range(bound, bound + 4)
    offset_ids = {offset: bound + 4 + offset for offset in range(11)}
    declarations = [(43, [scalar[0], count_id, 11]),
                    (28, [array_id, scalar[0], count_id]),
                    (32, [array_pointer_id, 6, array_id]),
                    (32, [scalar_pointer_id, 6, scalar[0]])]
    declarations.extend((43, [scalar[0], offset_ids[offset], offset]) for offset in range(11))
    out = list(words[:5])
    out[3] = bound + 15
    for _, op, operands in parsed:
        ops = list(operands)
        if op == 59 and ops[1] == variable:
            for declaration_op, declaration in declarations:
                out.extend([(len(declaration) + 1) << 16 | declaration_op, *declaration])
            ops[0], ops[2] = array_pointer_id, 6
        elif op == 65 and ops[1] in accesses:
            ops[0], ops[3] = scalar_pointer_id, offset_ids[accesses[ops[1]]]
        out.extend([(len(ops) + 1) << 16 | op, *ops])
    return out, {'accesses': len(accesses), 'workgroup_bytes_before': 45056,
                 'workgroup_bytes_after': 0, 'private_bytes_per_invocation': 44}

def main():
    base_in = os.path.join(REPO_ROOT, '.local', 'shaders_dump', 'shaders_dump')
    if not os.path.exists(base_in):
        base_in = os.path.join(REPO_ROOT, '.local', 'shaders_dump')
    
    work_dir = os.path.join(REPO_ROOT, '.local', 'compiled_shaders', 'work')
    out_dir = os.path.join(REPO_ROOT, '.local', 'compiled_shaders', 'xgs')
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    CS_MAGIC = bytes.fromhex('79563412')
    GFX_MAGIC = bytes.fromhex('78563412')
    SPH_STAGE = {1: 'vs', 2: 'hs', 3: 'ds', 4: 'gs', 5: 'ps'}

    jobs = []
    shader_meta = {}
    skipped_count = 0

    for f in sorted(os.listdir(base_in)):
        if not f.endswith('.code.bin'):
            continue
        key = f.split('.')[0]
        with open(os.path.join(base_in, f'{key}.code.bin'), 'rb') as fp:
            code = fp.read()
        with open(os.path.join(base_in, f'{key}.control.bin'), 'rb') as fp:
            ctrl = fp.read()
        
        c1_off, code_len = struct.unpack_from('<II', ctrl, 0x700)
        c1 = code[c1_off:code_len] if code_len > c1_off and code_len <= len(code) else b''
        
        if code[:4] == CS_MAGIC:
            stage = 'cs'
            body = code[0x100:]
        elif code[:4] == GFX_MAGIC:
            w0 = struct.unpack_from('<I', code, 0x30)[0]
            st_no = (w0 >> 10) & 0xF
            if st_no == 0 and (w0 & 0x1F) == 1:
                stage = 'vs'
            elif st_no == 5 or (w0 & 0x1F) == 2:
                stage = 'ps'
            else:
                stage = SPH_STAGE.get(st_no, 'vs')
            body = code[0x30:]
        else:
            print(f'Skipping unknown magic in {key}')
            skipped_count += 1
            continue
        
        code_path = os.path.join(work_dir, f'{key}.body.bin')
        with open(code_path, 'wb') as fp:
            fp.write(body)
        
        job = {
            'key': key,
            'stage': stage,
            'code': code_path,
            'c1': c1.hex(),
            'debug': True,
            'reduced': True
        }
        if stage == 'cs':
            try:
                job.update(compute_metadata(ctrl))
            except ValueError as error:
                print(f'ERROR preparing {key}: {error}')
                return 1
        jobs.append(job)
        shader_meta[key] = (stage, c1)

    print(f'Prepared {len(jobs)} jobs. Running dmsh_xlate...')
    if not jobs:
        print('ERROR: no shader jobs were prepared')
        return 1

    job_file = os.path.join(work_dir, 'all_jobs.json')
    with open(job_file, 'w') as fp:
        json.dump(jobs, fp)

    env = dict(os.environ)
    env['PATH'] = '/Users/yuyan9923/.dotnet:' + env.get('PATH', '')
    env['DOTNET_ROOT'] = '/Users/yuyan9923/.dotnet'

    dotnet_bin = os.path.expanduser('~/.dotnet/dotnet')
    xlate_dll = os.path.join(REPO_ROOT, '.local', 'refs', 'nxnative', 'dm', 'gfx', 'tools', 'dmsh_xlate', 'bin', 'Release', 'net10.0', 'dmsh_xlate.dll')
    cmd = [dotnet_bin, xlate_dll, job_file, work_dir]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        print('dmsh_xlate failed:', res.stderr)
        return res.returncode

    success_count = 0
    for key, (stage, c1) in shader_meta.items():
        spv_path = os.path.join(work_dir, f'{key}.spv')
        res_path = os.path.join(work_dir, f'{key}.res.json')
        if not os.path.exists(spv_path):
            print(f'FAILED: {key} (no spv)')
            continue
        with open(spv_path, 'rb') as fp:
            spv_bytes = fp.read()
        with open(res_path, 'r') as fp:
            result = json.load(fp)
        
        try:
            words = build_ffrs_xgs.read_words(spv_bytes)
            words = build_ffrs_xgs.renumber_bindings(words, stage)
            words, layout_fixes = build_ffrs_xgs.isolate_workgroup_array_layout(words)
            if key == '1618f5e9ae2a6df7':
                words, scratch_fix = localize_1618_scratch(words)
                print(f'1618 invocation-private scratch: {scratch_fix}')
            original_declared = set(caps_tool.analyse(words)['declared'])
            unused = build_ffrs_xgs.provably_unused(words)
            words, trim_method = build_ffrs_xgs.trim_capabilities(words, None)
            words, fixes = build_ffrs_xgs.apply_device_fixes(words, original_declared, unused)
            spirv = build_ffrs_xgs.write_words(words)
            if key == '1618f5e9ae2a6df7':
                validation = subprocess.run(
                    ['spirv-val', '--target-env', 'vulkan1.1', '-'],
                    input=spirv, capture_output=True)
                if validation.returncode:
                    raise ValueError('1618 private scratch validation failed: ' +
                                     validation.stderr.decode('utf-8', errors='replace'))
            vk = build_ffrs_xgs.reflect(key, stage, c1, words, result, 'nvn')
            _, data = build_ffrs_xgs.pack(vk, spirv)
            out_xgs = os.path.join(out_dir, f'{key}.xgs')
            with open(out_xgs, 'wb') as fp:
                fp.write(data)
            build_ffrs_xgs.check_bundle(out_xgs, vk, spirv)
            success_count += 1
            print(f'OK: {key} ({stage}) -> {len(data)} bytes')
        except Exception as e:
            print(f'ERROR in reflect/pack {key} ({stage}): {e}')

    print(f'Total successfully packed: {success_count} / {len(jobs)}')
    if success_count != len(jobs) or skipped_count:
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
