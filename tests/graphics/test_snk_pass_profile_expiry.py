import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PassProfileExpiryTests(unittest.TestCase):
    def test_normal_paths_resume_after_bounded_capture(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('    // A bounded diagnostic restores')
        end = source.index('    if(provenance_file &&', start)
        program = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
struct { std::atomic<uint64_t> presents{0}; } stats;
bool pass_prof_enabled;
uint64_t pass_prof_until;
unsigned notes;
void xbg_logf(const char *,...) {++notes;}
void present_boundary() {
''' + source[start:end] + r'''
}
int main() {
    pass_prof_until=100;pass_prof_enabled=true;
    for(uint64_t i=0;i<100;i++){stats.presents=i;present_boundary();assert(pass_prof_enabled && !notes);}
    stats.presents=100;present_boundary();assert(!pass_prof_enabled && notes==1);
    stats.presents=101;present_boundary();assert(!pass_prof_enabled && notes==1);
    pass_prof_enabled=true;pass_prof_until=110;
    stats.presents=105;present_boundary();assert(pass_prof_enabled);
    stats.presents=111;present_boundary();assert(!pass_prof_enabled && notes==2);
    pass_prof_enabled=true;pass_prof_until=UINT64_MAX;
    stats.presents=100000;present_boundary();assert(pass_prof_enabled && notes==2);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'expiry.cpp').write_text(program)
            executable = path / 'expiry'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                            str(path / 'expiry.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
