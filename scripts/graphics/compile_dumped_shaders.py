#!/usr/bin/env python3
import sys, os, struct, json, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, SCRIPT_DIR)
import build_ffrs_xgs
import fix_spirv_capabilities as caps_tool

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
        jobs.append(job)
        shader_meta[key] = (stage, c1)

    print(f'Prepared {len(jobs)} jobs. Running dmsh_xlate...')

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
            original_declared = set(caps_tool.analyse(words)['declared'])
            unused = build_ffrs_xgs.provably_unused(words)
            words, trim_method = build_ffrs_xgs.trim_capabilities(words, None)
            words, fixes = build_ffrs_xgs.apply_device_fixes(words, original_declared, unused)
            spirv = build_ffrs_xgs.write_words(words)
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
    return 0

if __name__ == '__main__':
    sys.exit(main())
