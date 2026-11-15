import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PngDecoderTests(unittest.TestCase):
    def test_sdk_result_capacity_stride_and_lifetime(self):
        source = (ROOT / 'src/runtime/hle/snk_hle_media.c').read_text()
        implementation = source[source.index('struct snk_png_state {'):source.index('/* ====================================================================== */\n/* libc')]
        program = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <limits.h>
#include <pthread.h>
#include <assert.h>
#include <zlib.h>
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#define STBI_NO_SIMD
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
''' + implementation + r'''
int main(void) {
    static const unsigned char png[] = {137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,2,0,0,0,2,8,6,0,0,0,114,182,13,36,0,0,0,26,73,68,65,84,120,156,99,248,42,47,253,159,251,190,96,20,131,168,254,199,134,189,225,138,12,0,63,98,6,110,174,107,169,223,0,0,0,0,73,69,78,68,174,66,96,130};
    static const unsigned char pixels[] = {245,31,27,255,11,223,17,90,21,47,241,128,189,87,33,0};
    int owner=0, other=0;
    unsigned char output[40];
    memset(output,0xa7,sizeof(output));
    snk_png_decoder_ctor(&owner);
    snk_png_decoder_set_image_data(&owner,png,sizeof(png));
    assert(snk_png_decoder_analyze(&owner)==0);
    assert(snk_png_decoder_dimension(&owner)==((uint64_t)2<<32|2));
    assert(snk_png_decoder_row_stride(&owner)==8);
    // x2 is capacity, x3 is stride. Padding and trailing canaries must survive.
    assert(snk_png_decoder_decode(&owner,output,24,16)==0);
    assert(!memcmp(output,pixels,8));
    assert(!memcmp(output+16,pixels+8,8));
    for (unsigned i=8;i<16;++i) assert(output[i]==0xa7);
    for (unsigned i=24;i<sizeof(output);++i) assert(output[i]==0xa7);
    unsigned char preserved[40]; memcpy(preserved,output,sizeof(output));
    assert(snk_png_decoder_decode(&owner,output,23,16)!=0);
    assert(snk_png_decoder_decode(&owner,output,sizeof(output),7)!=0);
    assert(snk_png_decoder_decode(&owner,output,SIZE_MAX,SIZE_MAX)!=0);
    assert(!memcmp(output,preserved,sizeof(output)));
    assert(snk_png_decoder_decode(&owner,output,16,0)==0);
    assert(!memcmp(output,pixels,16));
    snk_png_decoder_ctor(&other);
    snk_png_decoder_set_image_data(&other,"invalid",7);
    assert(snk_png_decoder_analyze(&other)!=0);
    assert(snk_png_decoder_dimension(&other)==0);
    snk_png_decoder_dtor(&owner);
    assert(snk_png_decoder_dimension(&owner)==0);
    snk_png_decoder_ctor(&owner);
    assert(snk_png_decoder_analyze(&owner)!=0);
    snk_png_decoder_dtor(&owner);
    snk_png_decoder_dtor(&other);
    int encoder=0;
    snk_png_encoder_ctor(&encoder);
    const uint64_t dimension=(uint64_t)2<<32|2;
    // Exercise the game's RGB8 format and RGBA8 with source padding.
    for (int channels=3;channels<=4;++channels) {
        unsigned char source[32]; memset(source,0x6b,sizeof(source));
        for (int y=0;y<2;++y) for (int x=0;x<2;++x)
            memcpy(source+y*16+x*channels,pixels+(y*2+x)*4,(size_t)channels);
        snk_png_encoder_set_pixel_data(&encoder,source,sizeof(source),channels==3?10:14,dimension,16);
        size_t maximum=snk_png_encoder_size_max(&encoder);
        assert(maximum>57);
        unsigned char *encoded=malloc(maximum+16); assert(encoded);
        memset(encoded,0x35,maximum+16);
        size_t written=99;
        assert(snk_png_encoder_encode(&encoder,&written,encoded,maximum)==0);
        assert(written>57 && written<=maximum);
        for (size_t i=written;i<maximum+16;++i) assert(encoded[i]==0x35);
        snk_png_decoder_ctor(&other);
        snk_png_decoder_set_image_data(&other,encoded,written);
        assert(snk_png_decoder_analyze(&other)==0);
        assert(snk_png_decoder_decode(&other,output,sizeof(output),8)==0);
        for (int i=0;i<4;++i) {
            assert(!memcmp(output+i*4,pixels+i*4,3));
            assert(output[i*4+3]==(channels==3?255:pixels[i*4+3]));
        }
        unsigned char before[32]; memcpy(before,encoded,sizeof(before));
        assert(snk_png_encoder_encode(&encoder,&written,encoded,57)!=0);
        assert(written==0 && !memcmp(before,encoded,sizeof(before)));
        snk_png_decoder_dtor(&other); free(encoded);
    }
    // Verify native 16-bit input becomes network-order PNG samples.
    uint16_t samples[4]={0x1234,0xabcd,0x0080,0xff01};
    snk_png_encoder_set_pixel_data(&encoder,samples,sizeof(samples),9,dimension,4);
    size_t maximum=snk_png_encoder_size_max(&encoder);
    unsigned char *encoded=malloc(maximum); assert(encoded);
    size_t written;
    assert(snk_png_encoder_encode(&encoder,&written,encoded,maximum)==0);
    int w,h,channels;
    uint16_t *decoded=stbi_load_16_from_memory(encoded,(int)written,&w,&h,&channels,1);
    assert(decoded && w==2 && h==2 && !memcmp(samples,decoded,sizeof(samples)));
    stbi_image_free(decoded); free(encoded);
    // Packed 1-bit grayscale includes two non-byte-aligned pixels per row.
    unsigned char packed[2]={0x40,0x80};
    snk_png_encoder_set_pixel_data(&encoder,packed,sizeof(packed),5,dimension,1);
    maximum=snk_png_encoder_size_max(&encoder);encoded=malloc(maximum);assert(encoded);
    assert(snk_png_encoder_encode(&encoder,&written,encoded,maximum)==0);
    unsigned char *gray=stbi_load_from_memory(encoded,(int)written,&w,&h,&channels,1);
    assert(gray && gray[0]==0 && gray[1]==255 && gray[2]==255 && gray[3]==0);
    stbi_image_free(gray);free(encoded);
    for (int format=1;format<=4;++format) {
        snk_png_encoder_set_pixel_data(&encoder,pixels,sizeof(pixels),format,dimension,8);
        assert(snk_png_encoder_size_max(&encoder)==0);
        assert(snk_png_encoder_encode(&encoder,&written,output,sizeof(output))!=0);
    }
    snk_png_encoder_set_pixel_data(&encoder,pixels,15,14,dimension,8);
    assert(snk_png_encoder_size_max(&encoder)==0);
    snk_png_encoder_set_pixel_data(&encoder,pixels,sizeof(pixels),14,dimension,7);
    assert(snk_png_encoder_size_max(&encoder)==0);
    snk_png_encoder_set_pixel_data(&encoder,pixels,SIZE_MAX,14,UINT64_MAX,SIZE_MAX);
    assert(snk_png_encoder_size_max(&encoder)==0);
    snk_png_encoder_dtor(&encoder);
    assert(snk_png_encoder_size_max(&encoder)==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'png.c').write_text(program)
            executable = path / 'png'
            subprocess.run([shutil.which('clang') or 'cc', '-std=c11',
                            '-fsanitize=address,undefined', '-pthread', '-I',
                            str(ROOT / 'third_party/stb'), str(path / 'png.c'),
                            '-lz', '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
