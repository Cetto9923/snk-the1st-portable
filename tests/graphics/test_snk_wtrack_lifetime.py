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
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'lifetime.cpp'
            source.write_text('''
#include <cstdint>
constexpr unsigned kMaxSlots=16;
struct Slot {bool pending=false, recording=false;};
Slot slots[kMaxSlots];
struct Version {unsigned last_slot=UINT32_MAX;};
''' + text[start:end] + '''
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
    v.last_slot=kMaxSlots;
    if (version_reusable(v)) return 5;
}
''')
            exe = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            str(source), '-o', str(exe)], check=True, capture_output=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
