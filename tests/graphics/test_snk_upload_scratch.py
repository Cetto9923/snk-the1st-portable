import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class UploadScratchTests(unittest.TestCase):
    def test_actual_upload_scope_reuse_reentrancy_threads_zeroing_and_limit(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        declaration = source.index('decoded_upload_scratch;')
        begin = source.rfind('\n', 0, declaration) + 1
        end = source.index('std::vector<VkBufferImageCopy> copies;', begin) + len('std::vector<VkBufferImageCopy> copies;')
        prefix = source[begin:end]
        start_return = source.index('        // GPU uploads refer to staging storage,', end)
        end_return = source.index('\n    }\n    // Canary:', start_return)
        suffix = source[start_return:end_return]
        staging = source.index('Buffer staging=stream_buffer(linear.size(),linear.data(),linear.size(),false);', end)
        self.assertLess(staging, start_return)
        self.assertGreater(begin, source.index('    if(upload && !im.uploaded && !im.gpu_written){'))
        program = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <thread>
#include <vector>
struct VkBufferImageCopy {};
struct Image { bool decoded; };
struct Observation { size_t capacity=0;const uint8_t *data=nullptr; };
static std::vector<uint8_t> upload(size_t size,uint8_t value,bool decoded,
                                  size_t nested,bool fail,Observation &observation){
    Image im{decoded};
''' + prefix + r'''
    observation.capacity=linear.capacity();observation.data=linear.data();
    assert(linear.empty());
    linear.resize(size);
    assert(std::all_of(linear.begin(),linear.end(),[](uint8_t v){return v==0;}));
    for(size_t i=0;i<linear.size();++i)linear[i]=uint8_t(value+i%251);
    if(nested){
        Observation inner;
        auto result=upload(nested,93,true,0,false,inner);
        if(decoded)assert(inner.capacity==0);
        for(size_t i=0;i<result.size();++i)assert(result[i]==uint8_t(93+i%251));
        for(size_t i=0;i<linear.size();++i)assert(linear[i]==uint8_t(value+i%251));
    }
    if(fail)throw std::runtime_error("injected CPU upload preparation failure");
    auto staged=linear; // Production stream_buffer copies the bytes before reuse.
''' + suffix + r'''
    return staged;
}
int main(){
    Observation first,second,raw,after_raw,outer,after_nested,huge,after_huge;
    auto one=upload(4096,7,true,0,false,first);assert(first.capacity==0);
    auto two=upload(512,11,true,0,false,second);assert(second.capacity>=4096);
    for(size_t i=0;i<one.size();++i)assert(one[i]==uint8_t(7+i%251));
    for(size_t i=0;i<two.size();++i)assert(two[i]==uint8_t(11+i%251));
    upload(1024,17,false,0,false,raw);assert(raw.capacity==0);
    upload(256,19,true,0,false,after_raw);assert(after_raw.capacity>=4096);
    upload(8192,23,true,16384,false,outer);
    upload(128,29,true,0,false,after_nested);assert(after_nested.capacity>=16384);
    upload(2048,30,false,128,false,raw);assert(raw.capacity==0);
    upload(32768,31,true,64,false,outer);
    upload(128,37,true,0,false,after_nested);assert(after_nested.capacity>=32768);
    Observation failed,after_failure;
    try{upload(2048,41,true,0,true,failed);assert(false);}catch(const std::runtime_error &){}
    upload(128,43,true,0,false,after_failure);assert(after_failure.capacity==0);
    upload(33u*1024u*1024u,47,true,0,false,huge);
    upload(256,53,true,0,false,after_huge);assert(after_huge.capacity==0);
    Observation other_first,other_second,main_after_thread;
    std::thread worker([&]{
        upload(16384,59,true,0,false,other_first);assert(other_first.capacity==0);
        upload(128,61,true,0,false,other_second);assert(other_second.capacity>=16384);
    });worker.join();
    upload(128,67,true,0,false,main_after_thread);
    assert(main_after_thread.capacity>=256 && main_after_thread.capacity<16384);
    std::thread left([]{Observation a,b;upload(1024,71,true,0,false,a);assert(a.capacity==0);upload(128,73,true,0,false,b);assert(b.capacity>=1024);});
    std::thread right([]{Observation a,b;upload(8192,79,true,0,false,a);assert(a.capacity==0);upload(128,83,true,0,false,b);assert(b.capacity>=8192);});
    left.join();right.join();
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'scratch.cpp'
            code.write_text(program)
            executable = path / 'scratch'
            compiled = subprocess.run(['clang++', '-std=c++17', '-pthread', '-fsanitize=address,undefined',
                                       str(code), '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
