import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class MovieColorTests(unittest.TestCase):
    def test_matrices_ranges_and_capacity(self):
        program = r'''
#include "movie_nv12.h"
#include <array>
#include <cassert>
#include <cmath>
#include <cstring>
#include <vector>
int main(){
    const unsigned width=16,height=8;
    std::vector<uint8_t> nv12(width*height*3/2),rgba(width*height*4+16,0x79);
    for(size_t i=0;i<nv12.size();++i)nv12[i]=uint8_t((i*71+39)%256);
    for(int standard:{1,2,4,6})for(int range:{1,2}){
        assert(movie_nv12_to_rgba(nv12.data(),nv12.size(),rgba.data(),rgba.size()-16,width,height,standard,range));
        double kr=standard==1?.2126:standard==6?.2627:.299;
        double kb=standard==1?.0722:standard==6?.0593:.114;
        double kg=1-kr-kb,ys=range==2?255.0/219:1,cs=range==2?255.0/224:1;
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x){
            size_t c=width*height+(y/2)*width+(x&~1u),pixel=(y*width+x)*4;
            double l=(int(nv12[y*width+x])-(range==2?16:0))*ys;
            double u=int(nv12[c])-128,v=int(nv12[c+1])-128;
            std::array<double,3> reference={l+2*(1-kr)*cs*v,
                l-2*kb*(1-kb)/kg*cs*u-2*kr*(1-kr)/kg*cs*v,l+2*(1-kb)*cs*u};
            for(unsigned channel=0;channel<3;++channel){
                int expected=int(std::lround(std::clamp(reference[channel],0.0,255.0)));
                assert(std::abs(int(rgba[pixel+channel])-expected)<=1);
            }
            assert(rgba[pixel+3]==255);
        }
        for(size_t i=width*height*4;i<rgba.size();++i)assert(rgba[i]==0x79);
    }
    auto preserved=rgba;
    assert(!movie_nv12_to_rgba(nv12.data(),nv12.size()-1,rgba.data(),rgba.size(),width,height,1,2));
    assert(!movie_nv12_to_rgba(nv12.data(),nv12.size(),rgba.data(),width*height*4-1,width,height,1,2));
    assert(!movie_nv12_to_rgba(nv12.data(),nv12.size(),rgba.data(),rgba.size(),width-1,height,1,2));
    assert(!movie_nv12_to_rgba(nv12.data(),nv12.size(),rgba.data(),rgba.size(),width,height,-1,2));
    assert(!movie_nv12_to_rgba(nv12.data(),nv12.size(),rgba.data(),rgba.size(),width,height,1,3));
    assert(!movie_nv12_to_rgba(nv12.data(),nv12.size(),rgba.data(),rgba.size(),UINT32_MAX,UINT32_MAX,1,2));
    assert(rgba==preserved);
    for(unsigned w:{16u,1920u,3840u}){
        unsigned h=2;size_t pixels=w*h;
        std::vector<uint8_t> input(pixels*3/2,63),expected(pixels*4),actual(pixels*4);
        for(size_t p=pixels;p<input.size();p+=2){input[p]=102;input[p+1]=240;}
        int standard=w>=3840?6:w>720?1:2;
        assert(movie_nv12_to_rgba(input.data(),input.size(),expected.data(),expected.size(),w,h,standard,2));
        assert(movie_nv12_to_rgba(input.data(),input.size(),actual.data(),actual.size(),w,h,0,0));
        assert(expected==actual);
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'movie_color.cpp').write_text(program)
            executable = path / 'movie_color'
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-I', str(ROOT / 'src/runtime/hle'),
                            str(path / 'movie_color.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
