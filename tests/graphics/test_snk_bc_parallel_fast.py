import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class BcParallelFastTests(unittest.TestCase):
    def test_actual_decoder_formats_edges_strides_threads_and_overrides(self):
        engine = ROOT / 'src/graphics/nvn_vulkan/engine'
        source = (engine / 'xbg_texture.c').read_text()
        signature = 'static int bc_fast_block(uint32_t fmt,const uint8_t *b,uint8_t *d,size_t pitch) {'
        self.assertEqual(source.count(signature), 1)
        source = source.replace(signature, signature + '\n    atomic_fetch_add(&fast_calls,1);')
        program = r'''
#include <pthread.h>
#include <assert.h>
#include <stdatomic.h>
#ifdef __APPLE__
#define pthread_setname_np(thread, name) pthread_setname_np(name)
#endif
static atomic_uint fast_calls;
''' + source + r'''
void dm_prof_add(int id,uint64_t ns,uint64_t bytes){(void)id;(void)ns;(void)bytes;}
static void check(uint32_t fmt,uint32_t w,uint32_t h,uint32_t depth,int fast){
    xbg_bc_format info;assert(!xbg_bc_format_info(fmt,&info));
    size_t blocks=(w+3)/4,rows=(h+3)/4,row=blocks*info.bytes_per_block+32;
    size_t image=row*rows+48,bytes=image*depth,out_bytes=(size_t)w*h*depth*info.bytes_per_pixel;
    uint8_t *source=malloc(bytes),*actual=malloc(out_bytes+64),*reference=malloc(out_bytes);
    assert(source && actual && reference);
    uint32_t random=fmt*21701u+w*71u+h;
    for(size_t i=0;i<bytes;i++){random^=random<<13;random^=random>>17;random^=random<<5;source[i]=random;}
    bc_job j={0};j.fmt=fmt;j.w=w;j.h=h;j.depth=depth;j.src=source;j.row=row;j.image=image;
    j.blocks=blocks;j.rows=rows;j.units=((rows+3)/4)*depth;j.bpp=info.bytes_per_pixel;
    j.block_bytes=info.bytes_per_block;j.dst=reference;j.fast=0;
    for(size_t u=0;u<j.units;u++)assert(!bc_rows(&j,u));
    unsigned before=atomic_load(&fast_calls);
    memset(actual,0x9d,out_bytes+64);
    assert(!xbg_decode_bc_linear(fmt,w,h,depth,source,bytes,row,image,actual,out_bytes));
    assert(!memcmp(actual,reference,out_bytes));
    for(size_t i=out_bytes;i<out_bytes+64;i++)assert(actual[i]==0x9d);
    unsigned attempted=atomic_load(&fast_calls)-before;
    if(fast && info.bytes_per_pixel==4)assert(attempted==(w/4)*(h/4)*depth);
    else assert(!attempted);
    size_t needed=image*(depth-1)+row*(rows-1)+blocks*info.bytes_per_block;
    assert(xbg_decode_bc_linear(fmt,w,h,depth,source,needed-1,row,image,actual,out_bytes)<0);
    assert(xbg_decode_bc_linear(fmt,w,h,depth,source,bytes,row,image,actual,out_bytes-1)<0);
    assert(xbg_decode_bc_linear(fmt,w,h,depth,source,bytes,row-1,image,actual,out_bytes)<0);
    assert(xbg_decode_bc_linear(fmt,w,h,depth,NULL,bytes,row,image,actual,out_bytes)<0);
    free(reference);free(actual);free(source);
}
int main(int argc,char **argv){
    assert(argc==3);int expected_workers=atoi(argv[1]),fast=atoi(argv[2]);
    for(unsigned repeat=0;repeat<3;repeat++)for(uint32_t fmt=0x41;fmt<=0x50;fmt++){
        check(fmt,1,3,1,fast);check(fmt,4,4,1,fast);
        check(fmt,65,67,2,fast);check(fmt,257,259,3,fast);
    }
    assert(bc_threads==(unsigned)expected_workers);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'decoder.c').write_text(program)
            executable = path / 'decoder'
            compiled = subprocess.run([
                'clang', '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-D_DARWIN_C_SOURCE', '-fsigned-char',
                '-pthread', '-fsanitize=address,undefined', '-I', str(engine),
                str(path / 'decoder.c'), str(engine.parent / 'tex/nvn_deswizzle.c'),
                str(engine.parent / 'nvn/nvn_tex.c'), '-lm', '-o', str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            configurations = [
                (None, '1', None, 0, '0', '0'),
                (None, '1', None, 2, '0', '1'),
                (None, '1', '0', 0, '0', '1'),
                ('0', '1', None, 0, '0', '1'),
                ('0', '1', None, 0, '0', '0'), ('2', '1', None, 2, '0', '0'),
                ('2', '0', None, 2, '0', '0'), ('0', '1', '2', 2, '0', '0'),
                ('2', '1', '0', 0, '0', '0'), ('0', '1', '9', 0, '0', '0'),
                ('0', '1', 'invalid', 0, '0', '0'), ('2', '1', None, 2, '1', '0'),
            ]
            for workers, fast, marker, expected, verify, profile in configurations:
                with self.subTest(workers=workers, fast=fast, marker=marker, verify=verify, profile=profile):
                    marker_path = path / 'gfx-bc-threads'
                    if marker is None:
                        if marker_path.exists():
                            marker_path.unlink()
                    else:
                        marker_path.write_text(marker)
                    env = os.environ.copy()
                    env.update(DM_BC_FAST=fast, DM_BC_VERIFY='0',
                               DM_BC_FASTVERIFY=verify, FFRS_APP_FILES_DIR=str(path),
                               FFRS_PROFILE_RG477M=profile)
                    if workers is None:
                        env.pop('DM_BC_THREADS', None)
                    else:
                        env['DM_BC_THREADS'] = workers
                    run = subprocess.run([str(executable), str(expected), fast],
                                         env=env, capture_output=True, text=True, timeout=40)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertIn('BC decode workers=' + str(expected), run.stderr)


if __name__ == '__main__':
    unittest.main()
