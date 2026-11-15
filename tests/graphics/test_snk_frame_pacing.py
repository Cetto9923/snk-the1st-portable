import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class FramePacingTests(unittest.TestCase):
    def test_elapsed_sleep_interruption_deadlines_and_unthrottled_override(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('static uint64_t xbg_frame_pace()')
        end = source.index('// gfx-flame-diag:', start)
        program = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <ctime>
static uint64_t s_target_frame_ns=33333333,s_next_present_ns,fake_now=1000000000;
static uint32_t s_pace_check_counter;
static unsigned refreshes,sleeps;
static bool interrupt_next;
static int (*nvn_android_pacing_target)(uint64_t)=nullptr;
static bool sdk_active;
static uint64_t sdk_target_ns;
static int sdk_target(uint64_t interval){sdk_target_ns=interval;return sdk_active && interval;}
static void xbg_refresh_target_fps(){++refreshes;}
static int clock_read(clockid_t,struct timespec *time){time->tv_sec=fake_now/1000000000;time->tv_nsec=fake_now%1000000000;return 0;}
static int sleep_for(const struct timespec *request,struct timespec *remaining){
    ++sleeps;uint64_t ns=uint64_t(request->tv_sec)*1000000000+uint64_t(request->tv_nsec);
    if(interrupt_next){interrupt_next=false;fake_now+=ns/2;ns-=ns/2;remaining->tv_sec=ns/1000000000;remaining->tv_nsec=ns%1000000000;errno=EINTR;return -1;}
    fake_now+=ns;return 0;
}
#define clock_gettime clock_read
#define nanosleep sleep_for
''' + source[start:end] + r'''
int main(){
    assert(xbg_frame_pace()==0 && sleeps==0 && refreshes==1);
    assert(s_next_present_ns==1033333333);
    fake_now+=10000000;interrupt_next=true;
    assert(xbg_frame_pace()==23333333 && sleeps==2);
    assert(fake_now==1033333333 && s_next_present_ns==1066666666);
    fake_now=s_next_present_ns+3*s_target_frame_ns;
    uint64_t stall=fake_now;assert(xbg_frame_pace()==0);
    assert(s_next_present_ns==stall+s_target_frame_ns);
    fake_now+=1000000;assert(xbg_frame_pace()==s_target_frame_ns-1000000);
    s_target_frame_ns=0;unsigned before=sleeps;assert(xbg_frame_pace()==0 && sleeps==before);
    for(unsigned i=0;i<60;++i)xbg_frame_pace();
    assert(refreshes==2);
    nvn_android_pacing_target=sdk_target;
    s_target_frame_ns=33333333;s_next_present_ns=0;
    before=sleeps;assert(xbg_frame_pace()==0 && sleeps==before);
    assert(s_next_present_ns==fake_now+s_target_frame_ns && sdk_target_ns==s_target_frame_ns);
    sdk_active=true;
    assert(xbg_frame_pace()==0 && sleeps==before && s_next_present_ns==0);
    s_target_frame_ns=0;
    assert(xbg_frame_pace()==0 && sleeps==before && sdk_target_ns==0);
    sdk_active=false;s_target_frame_ns=33333333;
    assert(xbg_frame_pace()==0 && s_next_present_ns==fake_now+s_target_frame_ns);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'pace.cpp').write_text(program)
            executable = path / 'pace'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                            str(path / 'pace.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
