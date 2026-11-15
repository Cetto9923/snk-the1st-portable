import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class EventGuardTests(unittest.TestCase):
    def test_fault_ownership_and_failed_unprotect(self):
        text = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = text.index('int fault(void *a,int w,void *uc){')
        end = text.index('\n}', start)
        function = text[start:end]
        program = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
constexpr int slots_n=4,PROT_READ=1,PROT_WRITE=2;
std::atomic<uintptr_t> page[slots_n]{},word[slots_n]{};
std::atomic<uint64_t> exact{0},other{0},writes{0};
std::atomic<uintptr_t> last_addr{0},last_word{0};
std::atomic<bool> reopened[slots_n]{};
uintptr_t pg(uintptr_t address){return address&~uintptr_t(4095);}
int protection_calls=0,protection_result=0;
int mprotect(void *,size_t,int){++protection_calls;return protection_result;}
''' + function + r'''
int main(){
    assert(!fault(reinterpret_cast<void*>(0xc4),0,nullptr));
    assert(!protection_calls && !other && !exact);
    page[0]=0x10000;word[0]=0x10100;
    assert(!fault(reinterpret_cast<void*>(0xc4),0,nullptr));
    assert(!fault(reinterpret_cast<void*>(0x20000),0,nullptr));
    assert(!protection_calls);
    assert(fault(reinterpret_cast<void*>(0x10100),0,nullptr));
    assert(protection_calls==1 && exact==1 && reopened[0]);
    reopened[0]=false;protection_result=-1;
    assert(!fault(reinterpret_cast<void*>(0x10180),1,nullptr));
    assert(protection_calls==2 && !reopened[0]);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'guard.cpp'
            source.write_text(program)
            executable = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', str(source), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)
