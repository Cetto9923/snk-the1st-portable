import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class EventPollTests(unittest.TestCase):
    def test_pending_value_and_submission_progress(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('extern "C" void xbg_game_event_poll(')
        end = source.index('\nextern "C" ', start + 1)
        implementation = source[start:end]
        program = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <mutex>
#include <future>
#include <thread>
#include <vector>
struct PendingEvent {uint64_t addr;uint32_t mode,v;const void *slot;};
static std::vector<PendingEvent> recording_events,pending_events;
static std::recursive_mutex mutex;
static bool initialized=false,failed=false,ready=false,gfx_async=false;
static unsigned submissions=0,polls=0,drains=0,opens=0;
static void gfx_drain(){++drains;}
static void submit_slots(bool wait){
    assert(!wait);++submissions;
    pending_events.insert(pending_events.end(),recording_events.begin(),recording_events.end());
    recording_events.clear();
}
static void poll_retire(){
    ++polls;
    if(!ready)return;
    for(auto &event:pending_events)*reinterpret_cast<uint32_t*>(event.addr)=event.v;
    pending_events.clear();
}
namespace evguard {static void unguard(uint64_t){++opens;}}
''' + implementation + r'''
int main(){
    uint32_t value=7,other=9;
    xbg_game_event_poll(&value);
    assert(drains==1 && submissions==0 && polls==0 && opens==0);
    initialized=true;
    recording_events.push_back({uint64_t(uintptr_t(&value)),0,19,nullptr});
    xbg_game_event_poll(&other);
    assert(submissions==0 && value==7 && recording_events.size()==1);
    xbg_game_event_poll(&value);
    assert(submissions==1 && value==7 && recording_events.empty() && pending_events.size()==1);
    xbg_game_event_poll(&value);
    assert(submissions==1 && value==7 && pending_events.size()==1);
    ready=true;
    xbg_game_event_poll(&value);
    assert(submissions==1 && value==19 && pending_events.empty());
    failed=true;unsigned previous=polls;
    xbg_game_event_poll(&value);assert(polls==previous);
    failed=false;ready=false;gfx_async=true;
    unsigned old_drains=drains,old_submissions=submissions,old_polls=polls;
    recording_events.push_back({uint64_t(uintptr_t(&value)),0,29,nullptr});
    std::promise<void> locked,release;
    auto release_future=release.get_future();
    std::thread translator([&]{
        std::lock_guard<std::recursive_mutex> lock(mutex);
        locked.set_value();release_future.wait();
    });
    locked.get_future().wait();
    // Must return while the translator still owns the engine. A blocking
    // poll deadlocks here and is rejected by the test process timeout.
    xbg_game_event_poll(&value);
    assert(drains==old_drains && submissions==old_submissions && polls==old_polls);
    assert(value==19);
    release.set_value();translator.join();
    xbg_game_event_poll(&value);
    assert(drains==old_drains && submissions==old_submissions+1 && value==19);
    ready=true;xbg_game_event_poll(&value);assert(value==29);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'event_poll.cpp').write_text(program)
            executable = path / 'event_poll'
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-pthread',
                            str(path / 'event_poll.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
