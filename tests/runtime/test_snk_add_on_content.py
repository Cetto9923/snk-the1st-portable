import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class AddOnContentTests(unittest.TestCase):
    def test_imported_indices_pagination_validation_and_read_only_mounts(self):
        source = (ROOT / 'src/runtime/hle/nso_host.c').read_text()
        start = source.index('/* Each locally imported add-on')
        end = source.index('/* nn::os::SystemEvent', start)
        declarations = source[source.index('#define NSO_FS_MAX_MOUNTS'):source.index('int32_t nso_host_fs_get_save_data_size')]
        program = r'''
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
''' + declarations + source[start:end] + r'''
static void install(int index) {
    char path[256];
    snprintf(path,sizeof(path),"aoc/%d",index);assert(!mkdir(path,0700));
    snprintf(path,sizeof(path),"aoc/%d/romfs",index);assert(!mkdir(path,0700));
    snprintf(path,sizeof(path),"aoc/%d/content-id",index);
    FILE *file=fopen(path,"wb");assert(file);
    fprintf(file,"%016" PRIx64 "\n",UINT64_C(0x01001e9023921000)+index);fclose(file);
}
int main(void) {
    assert(!mkdir("romfs",0700));assert(!setenv("NN_FS_ROM_PATH","romfs",1));
    assert(nso_host_aoc_count_add_on_content()==0);
    assert(!mkdir("aoc",0700));
    for(int i=98;i>0;--i)install(i);
    assert(nso_host_aoc_count_add_on_content()==98);
    int32_t values[101];for(int i=0;i<101;i++)values[i]=-999;
    assert(nso_host_aoc_list_add_on_content(values,0,101)==98);
    for(int i=0;i<98;i++)assert(values[i]==i+1);
    assert(values[98]==-999);
    assert(nso_host_aoc_list_add_on_content(values,97,INT32_MAX)==1 && values[0]==98);
    assert(!nso_host_aoc_list_add_on_content(values,-1,5));
    assert(!nso_host_aoc_list_add_on_content(values,98,5));
    assert(!nso_host_aoc_list_add_on_content(NULL,0,5));
    assert(!nso_host_aoc_list_add_on_content(values,0,0));
    assert(!nso_host_aoc_list_add_on_content(values,INT32_MAX,5));
    size_t size=99;assert(!nso_host_fs_query_mount_add_on_content_cache_size(&size,1) && !size);
    assert(nso_host_fs_query_mount_add_on_content_cache_size(NULL,1));
    assert(nso_host_fs_query_mount_add_on_content_cache_size(&size,-1)==0x202);
    assert(nso_host_fs_mount_add_on_content("absent",1000,NULL,0)==0x202);
    assert(nso_host_fs_mount_add_on_content("bad/name",1,NULL,0));
    for(int i=1;i<=98;i++) {
        char name[32];snprintf(name,sizeof(name),"dlc%d",i);
        assert(!nso_host_fs_mount_add_on_content(name,i,NULL,0));
        assert(!nso_host_fs_mount_add_on_content(name,i,NULL,0));
    }
    assert(nso_host_fs_mount_add_on_content("dlc1",2,NULL,0));
    for(int i=0;i<98;i++)assert(s_fs_mounts[i].in_use && !s_fs_mounts[i].writable);
    assert(!unlink("aoc/1/content-id"));assert(nso_host_aoc_count_add_on_content()==97);
    assert(!rmdir("aoc/2/romfs"));assert(nso_host_aoc_count_add_on_content()==96);
    FILE *file=fopen("aoc/3/content-id","wb");assert(file);fputs("01001e9023921004\n",file);fclose(file);
    assert(nso_host_aoc_count_add_on_content()==95);
    assert(!mkdir("aoc/0004",0700));assert(!mkdir("aoc/-1",0700));
    assert(!mkdir("aoc/2048",0700));assert(nso_host_aoc_count_add_on_content()==95);
    assert(!setenv("NN_FS_ROM_PATH","missing/romfs",1));assert(nso_host_aoc_count_add_on_content()==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'aoc.c').write_text(program)
            subprocess.run(['clang', '-std=c11', '-D_DARWIN_C_SOURCE', '-Wall', '-Wextra',
                            '-Wno-unused-variable', '-fsanitize=address,undefined',
                            str(path / 'aoc.c'), '-o', str(path / 'aoc-test')],
                           check=True, capture_output=True)
            subprocess.run([str(path / 'aoc-test')], cwd=path, check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
