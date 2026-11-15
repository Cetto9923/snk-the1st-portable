import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class WriteTrackLifetimeTests(unittest.TestCase):
    def test_reuse_requires_retired_last_reader(self):
        text = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = text.index('bool version_reusable(')
        end = text.index('struct Tracked{', start)
        begin = text.index('        s.recording=true;s.ops=0;s.generation=slot_serial;')
        recording = text[begin:text.index('\n', begin)]
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'lifetime.cpp'
            source.write_text('''
#include <cstdint>
constexpr unsigned kMaxSlots=16;
struct Slot {bool pending=false, recording=false;uint64_t generation=0,ops=0;};
Slot slots[kMaxSlots];
struct Version {unsigned last_slot=UINT32_MAX;uint64_t last_use=0;};
''' + text[start:end] + '''
void begin_recording() {
    Slot &s=slots[0];uint64_t slot_serial=1;
''' + recording + '''
}
int main() {
    Version v;
    if (!version_reusable(v)) return 1;
    v.last_slot=0;
    slots[0].pending=true;
    if (version_reusable(v)) return 2;
    slots[0].pending=false;
    slots[0].recording=true;
    if (version_reusable(v)) return 3;
    slots[0].recording=false;
    if (!version_reusable(v)) return 4;
    // Reusing the physical slot proves the older generation retired.
    begin_recording();
    if (!version_reusable(v)) return 5;
    // A new read of the same version remains protected through its own fence.
    v.last_use=1;
    if (version_reusable(v)) return 6;
    slots[0].recording=false;slots[0].pending=true;
    if (version_reusable(v)) return 7;
    slots[0].pending=false;
    if (!version_reusable(v)) return 8;
    v.last_slot=kMaxSlots;
    if (version_reusable(v)) return 9;
}
''')
            exe = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17', '-fsanitize=address,undefined',
                            str(source), '-o', str(exe)], check=True, capture_output=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
