import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PointerDefaultsTests(unittest.TestCase):
    def test_platform_default_and_marker(self):
        source = (ROOT / 'src/android/native/guest_boot_jni.cpp').read_text()
        start = source.index('        const std::string pointer_marker =')
        end = source.index('        fprintf(stderr, "[port] original_allocator', start)
        block = source[start:end]
        program = r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#define PROP_VALUE_MAX 92
void configure(const std::string &path) {
''' + block + r'''
}
int main(int argc,char **argv) {
    assert(argc==2);std::string path=argv[1],marker=path+"/hle-original-pointer-tests";
    configure(path);
    assert(atoi(getenv("SNK_ORIGINAL_POINTER_TESTS"))==1);
    for(char c:{'0','1'}) {FILE *f=fopen(marker.c_str(),"wb");assert(f);fputc(c,f);fclose(f);configure(path);assert(atoi(getenv("SNK_ORIGINAL_POINTER_TESTS"))==c-'0');}
    remove(marker.c_str());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'gate.cpp').write_text(program)
            executable = path / 'gate'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                            str(path / 'gate.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable), directory], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
