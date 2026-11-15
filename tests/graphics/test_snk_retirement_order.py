import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RetirementOrderTests(unittest.TestCase):
    def test_wrapped_poll_preserves_writeback_and_completion_order(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('void poll_retire(){')
        end = source.index('\nvoid execute(', start)
        program = r'''
#include <cassert>
#include <cstdint>
#include <mutex>
#include <vector>
struct Slot {bool pending=false,recording=false;int fence=0;uint64_t sequence=0;};
Slot slots[16];unsigned slot_count,slot_index;
struct { int device; } cfg;
constexpr int VK_SUCCESS=0,VK_NOT_READY=1;
int status[16];unsigned polls,notifications;
int vkGetFenceStatus(int,int fence){++polls;return status[fence];}
std::mutex gfx_job_mutex;
struct {void notify_all(){++notifications;}} gfx_idle_cv;
std::vector<uint64_t> retired;
uint64_t completed,cpu_result;
void retire_slot(Slot &slot){
    assert(slot.sequence>completed);
    completed=cpu_result=slot.sequence;retired.push_back(slot.sequence);slot.pending=false;
}
''' + source[start:end] + r'''
void setup(unsigned count,unsigned next) {
    slot_count=count;slot_index=next;polls=notifications=0;completed=cpu_result=0;retired.clear();
    for(unsigned i=0;i<16;i++){slots[i]=Slot{};slots[i].fence=i;status[i]=VK_SUCCESS;}
    for(unsigned i=0;i<count;i++){Slot &s=slots[(next+i)%count];s.pending=true;s.sequence=i+1;}
}
int main() {
    for(unsigned count:{2u,4u,16u})for(unsigned next=0;next<count;next++) {
        setup(count,next);poll_retire();assert(retired.size()==count && cpu_result==count && completed==count && notifications==1);
        for(unsigned i=0;i<count;i++)assert(retired[i]==i+1);
        unsigned before=polls;poll_retire();assert(polls==before && notifications==1);
        setup(count,next);status[next]=VK_NOT_READY;poll_retire();assert(retired.empty() && polls==1 && !notifications);
        status[next]=VK_SUCCESS;unsigned second=(next+1)%count;status[second]=VK_NOT_READY;
        poll_retire();assert(retired.size()==1 && completed==1 && notifications==1);
        status[second]=VK_SUCCESS;poll_retire();assert(retired.size()==count && completed==count && notifications==2);
        setup(count,next);slots[next].recording=true;poll_retire();assert(retired.empty() && !polls && !notifications);
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'retire.cpp').write_text(program)
            executable = path / 'retire'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined', '-pthread',
                            str(path / 'retire.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
