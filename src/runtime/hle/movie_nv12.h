#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

// Android color-standard 1/2/4/6 and color-range 1/2 select the YCbCr matrix.
// Input is tight NV12 and output is RGBA byte order, with independent storage.
inline bool movie_nv12_to_rgba(const uint8_t *source,size_t source_bytes,
    uint8_t *destination,size_t destination_bytes,uint32_t width,uint32_t height,
    int standard,int range){
    const uint64_t pixels=uint64_t(width)*height;
    if(!source || !destination || !width || !height || ((width|height)&1) ||
       pixels>SIZE_MAX/4 || pixels+pixels/2>source_bytes || pixels*4>destination_bytes)return false;
    // Match Android ColorUtils defaults when the decoder reports unspecified.
    // frameworks/av media/module/foundation/ColorUtils.cpp, blob12bffca197bd.
    if(!standard){
        if(width>=3840 || height>=3840 || pixels>=uint64_t(3840)*1634)standard=6;
        else if((width<=720 && height<=576) || (height<=720 && width<=576))standard=2;
        else standard=1;
    }
    if(!range)range=2;
    if(range!=1 && range!=2)return false;
    int red_v,green_u,green_v,blue_u;
    if(standard==1){
        red_v=range==2?459:403;green_u=range==2?55:48;
        green_v=range==2?136:120;blue_u=range==2?541:475;
    }else if(standard==2 || standard==4){
        red_v=range==2?409:359;green_u=range==2?100:88;
        green_v=range==2?208:183;blue_u=range==2?516:454;
    }else if(standard==6){
        red_v=range==2?430:377;green_u=range==2?48:42;
        green_v=range==2?167:146;blue_u=range==2?548:482;
    }else return false;
    const int scale=range==2?298:256,offset=range==2?16:0;
    const uint8_t *chroma=source+size_t(pixels);
    for(uint32_t row=0;row<height;++row){
        const uint8_t *luma=source+size_t(row)*width;
        const uint8_t *uv=chroma+size_t(row/2)*width;
        uint8_t *output=destination+size_t(row)*width*4;
        for(uint32_t column=0;column<width;++column){
            const int y=(int(luma[column])-offset)*scale;
            const int u=int(uv[column&~1u])-128,v=int(uv[(column&~1u)+1])-128;
            const size_t pixel=size_t(column)*4;
            output[pixel]=uint8_t(std::clamp((y+red_v*v+128)>>8,0,255));
            output[pixel+1]=uint8_t(std::clamp((y-green_u*u-green_v*v+128)>>8,0,255));
            output[pixel+2]=uint8_t(std::clamp((y+blue_u*u+128)>>8,0,255));
            output[pixel+3]=255;
        }
    }
    return true;
}
