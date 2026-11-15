import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEVICE = ROOT / 'src/graphics/nvn_device'
ENGINE = ROOT / 'src/graphics/nvn_vulkan/engine'


class AsyncSubmitTests(unittest.TestCase):
    def compile_run(self, source, cpp=False, extra=()):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            unit = path / ('test.cpp' if cpp else 'test.c')
            unit.write_text(source)
            executable = path / 'test'
            command = [shutil.which('clang++' if cpp else 'clang'),
                       '-std=c++17' if cpp else '-std=c11',
                       '-fsanitize=address,undefined', '-pthread',
                       '-ffunction-sections', '-fdata-sections',
                       '-I', str(DEVICE), '-I', str(ENGINE), str(unit)]
            command.extend(str(DEVICE / name) for name in extra)
            command.extend(['-Wl,-dead_strip' if sys.platform == 'darwin'
                            else '-Wl,--gc-sections', '-o', str(executable)])
            built = subprocess.run(command, capture_output=True)
            self.assertEqual(built.returncode, 0, built.stderr.decode())
            ran = subprocess.run([str(executable)], capture_output=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stderr.decode())

    def test_deferred_real_packages_nested_calls_and_multiple_batches(self):
        self.compile_run(r'''
#include "nvn_command_buffer.h"
#include "nvn_obj_ffrs.h"
#include "nvn_command_replay.h"
#include "nvn_queue.h"
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[8192];static int pool,buffer;
static unsigned removed,released,queued,event_refs;
void nvn_engine_event_reference(uint64_t address,int retain){
    assert(address==0x1234);
    if(retain)event_refs++;else{assert(event_refs);event_refs--;}
}
struct Job {uint64_t handles[64];int count;void (*release)(void *);void *owner;} jobs[4];
int nvn_trace_enabled(void){return 0;}
int nvn_memory_pool_info_of(const void *p,nvn_memory_pool_info *out){
    if(p!=&pool)return 0;*out=(nvn_memory_pool_info){memory,sizeof(memory),0,1};return 1;
}
void nvn_engine_pool_add(void *p,size_t n){assert(p&&n);}
void nvn_engine_pool_del(void *p){assert(p);removed++;}
void nvn_command_replay_get_stats(nvn_replay_stats *s){memset(s,0,sizeof(*s));}
int nvn_command_replay_run(uint64_t h){abort();}
int nvn_engine_submit_with_release(const uint64_t *handles,int count,
                                  void (*release)(void *),void *owner){
    assert(queued<4&&count<=64);struct Job *j=&jobs[queued++];
    j->count=count;memcpy(j->handles,handles,count*sizeof(*handles));
    j->release=release;j->owner=owner;return 1;
}
static uint64_t make(unsigned i){
    nvn_command_buffer_add_command_memory_storage(&buffer,&pool,i*64,64);
    nvn_command_buffer_begin_recording(&buffer);
    nvn_command_buffer_rec_report_value(&buffer,i,0x1234);
    return nvn_command_buffer_end_recording(&buffer);
}
static uint32_t read_value(uint64_t h){
    uint32_t value;memcpy(&value,(const void *)(uintptr_t)(h+20),4);return value;
}
int main(void){
    assert(nvn_command_buffer_initialize(&buffer));
    uint64_t handles[97];for(unsigned i=0;i<96;i++){handles[i]=make(i);assert(handles[i]);}
    uint64_t child=make(100);assert(child);
    nvn_command_buffer_add_command_memory_storage(&buffer,&pool,97*64,64);
    nvn_command_buffer_begin_recording(&buffer);
    nvn_command_buffer_rec_call_commands(&buffer,1,&child);
    handles[96]=nvn_command_buffer_end_recording(&buffer);assert(handles[96]);
    nvn_queue_submit_commands(NULL,97,handles);assert(queued==2&&event_refs==97);
    memset(handles,0,sizeof(handles));
    nvn_command_buffer_finalize(&buffer);
    nvn_command_buffer_retire_source_memory(memory,sizeof(memory));
    assert(removed==0);nvn_command_buffer_stats stats;
    nvn_command_buffer_get_stats(&stats);assert(stats.live_packages==98);
    unsigned sequence=0;
    for(unsigned i=0;i<queued;i++){
        struct Job *j=&jobs[i];
        for(int n=0;n<j->count;n++,sequence++){
            if(sequence<96)assert(read_value(j->handles[n])==sequence);
            else{
                uint64_t nested;memcpy(&nested,(const void *)(uintptr_t)(j->handles[n]+8),8);
                assert(nested==child&&read_value(nested)==100);
            }
        }
        j->release(j->owner);released++;
    }
    assert(sequence==97&&released==2&&removed==98&&!event_refs);
    nvn_command_buffer_get_stats(&stats);assert(!stats.live_packages&&!stats.package_bytes);
}
''', extra=('nvn_command_buffer.c', 'nvn_queue.c', 'nvn_sync.c'))

    def test_worker_order_borrowed_calls_shutdown_and_translation_deadline(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('bool gfx_async=false;')
        end = source.index('char error_text[', start)
        worker = source[start:end]
        start = source.index('extern "C" void xbg_submit_with_release(')
        end = source.index('extern "C" void xbg_present_texture(', start)
        submit = source[start:end]
        self.compile_run(r'''
#include "xbg_completion_wait.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <dlfcn.h>
#include <functional>
#include <mutex>
#include <pthread.h>
#include <thread>
#include <vector>
#define pthread_setname_np(a,b) ((void)0)
void xbg_logf(const char *,...){}
uint64_t submitted=0;
''' + worker + r'''
std::atomic<unsigned> delay_ms{1},consumed{0},released{0};
void xbg_submit_now(int n,const uint64_t *handles){
    std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
    assert(n==1&&handles[0]==consumed.load());++consumed;++submitted;
}
void release_test(void *p){assert(consumed.load()>uintptr_t(p));++released;}
''' + submit + r'''
int main(){
    gfx_async=true;gfx_worker=std::thread(gfx_worker_loop);
    delay_ms=80;uint64_t h=0;xbg_submit_with_release(1,&h,release_test,(void *)0);h=999;
    xbg_completion::Deadline poll(0);assert(!gfx_wait_translation(1,0,poll));
    xbg_completion::Deadline short_wait(2000000);
    auto start=std::chrono::steady_clock::now();
    assert(!gfx_wait_translation(1,2000000,short_wait));
    assert(std::chrono::steady_clock::now()-start<std::chrono::milliseconds(30));
    xbg_completion::Deadline long_wait(500000000);
    assert(gfx_wait_translation(1,500000000,long_wait)&&released==1);
    assert(!gfx_wait_translation(2,UINT64_MAX,long_wait));
    delay_ms=1;
    for(unsigned i=1;i<140;i++){
        h=i;xbg_submit_with_release(1,&h,release_test,(void *)(uintptr_t)i);h=999;
        assert(gfx_enqueued-gfx_executed<=64);
    }
    gfx_drain();assert(consumed==140&&released==140&&gfx_executed==gfx_enqueued);
    // A legacy caller's borrowed bytes are consumed before returning.
    h=140;xbg_submit(1,&h);assert(consumed==141&&gfx_executed==gfx_enqueued);
    h=141;xbg_submit_with_release(1,&h,release_test,(void *)(uintptr_t)141);
    gfx_async_stop();assert(consumed==142&&released==141&&!gfx_worker.joinable());
}
''', cpp=True)

    def test_idle_and_queued_event_references_preserve_gpu_completion(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('std::mutex event_reference_mutex;')
        end = source.index('struct PendingEvent', start)
        references = source[start:end]
        start = source.index('extern "C" void xbg_game_event_read(')
        end = source.index('extern "C" void xbg_game_event_poll(', start)
        read = source[start:end]
        self.compile_run(r'''
#include <cassert>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <vector>
void need(bool condition,const char *){assert(condition);}
''' + references + r'''
struct PendingEvent {uint64_t addr;uint32_t mode,v;const void *slot;};
std::vector<PendingEvent> pending_events,recording_events;
std::recursive_mutex mutex;
bool gfx_async=true,initialized=true,failed=false,translate_on_drain=false;
unsigned drains=0,event_reads=0,completions=0;
uint64_t target=0;
void gfx_drain(){
    ++drains;
    if(translate_on_drain){
        event_reference(target,true); // GPU publication inherits ownership.
        pending_events.push_back({target,0,29,nullptr});
        event_reference(target,false); // CPU command bytes are consumed.
        translate_on_drain=false;
    }
}
void complete_all(){
    ++completions;
    for(auto &event:pending_events){
        *reinterpret_cast<uint32_t *>(event.addr)=event.v;
        event_reference(event.addr,false);
    }
    pending_events.clear();
}
''' + read + r'''
int main(){
    uint32_t value=7,other=13;target=uintptr_t(&value);
    xbg_game_event_read(&value);assert(!drains&&!completions&&value==7);
    // An unexecuted command is visible before the worker has a PendingEvent.
    event_reference(target,true);translate_on_drain=true;
    xbg_game_event_read(&other);assert(!drains&&other==13);
    xbg_game_event_read(&value);
    assert(drains==1&&completions==1&&value==29&&!event_referenced(target));
    value=0;xbg_game_event_read(&value);assert(drains==1&&value==0);
    // Independent queued readers and repeated GPU writes cannot erase each other.
    event_reference(target,true);event_reference(target,true);event_reference(target,false);
    assert(event_referenced(target));event_reference(target,false);assert(!event_referenced(target));
    gfx_async=false;xbg_game_event_read(&value);assert(drains==2);
}
''', cpp=True)

    def test_engine_refusal_and_synchronous_release_once(self):
        source = (DEVICE / 'nvn_engine.c').read_text()
        start = source.index('int nvn_engine_submit_with_release(')
        end = source.index('void nvn_engine_pool_add(', start)
        self.compile_run(r'''
#include <assert.h>
#include <stdint.h>
static int ready,translated,released;
int nvn_engine_ready(void){return ready;}
void done(void *p){assert(p==(void *)0x1234);released++;}
void xbg_submit_with_release(int n,const uint64_t *h,void (*r)(void *),void *p){
    assert(n==1&&*h==12);translated++;r(p);
}
''' + source[start:end] + r'''
int main(void){
    uint64_t h=12;
    assert(!nvn_engine_submit_with_release(&h,1,done,(void *)0x1234));
    assert(released==1&&!translated);ready=1;
    assert(!nvn_engine_submit_with_release(0,1,done,(void *)0x1234));
    assert(!nvn_engine_submit_with_release(&h,0,done,(void *)0x1234));
    assert(released==3&&!translated);
    assert(nvn_engine_submit_with_release(&h,1,done,(void *)0x1234));
    assert(released==4&&translated==1);
}
''')


if __name__ == '__main__':
    unittest.main()
