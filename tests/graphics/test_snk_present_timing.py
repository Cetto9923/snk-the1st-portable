import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'src/graphics/nvn_device/nvn_backend_vulkan.c'


def function(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class PresentTimingTests(unittest.TestCase):
    def test_actual_schedule_and_application_marker_with_optional_engine(self):
        source = SOURCE.read_text()
        marker = function(source, 'static int nvn_vulkan_present_timing_requested(void)')
        schedule = function(source, 'static void nvn_vulkan_schedule_present(')
        program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <time.h>
#define VK_STRUCTURE_TYPE_PRESENT_TIMES_INFO_GOOGLE 1000092000
typedef struct { uint32_t presentID; uint64_t desiredPresentTime; } VkPresentTimeGOOGLE;
typedef struct { int sType; const void *pNext; uint32_t swapchainCount; const VkPresentTimeGOOGLE *pTimes; } VkPresentTimesInfoGOOGLE;
typedef struct { const void *pNext; unsigned waitSemaphoreCount; const void *pWaitSemaphores; unsigned swapchainCount; const void *pSwapchains; const void *pImageIndices; } VkPresentInfoKHR;
typedef struct { unsigned present_timing_active, present_timing_id; } nvn_vulkan_state;
#if defined(__APPLE__)
extern uint64_t xbg_desired_present_time_ns(void) __attribute__((weak_import));
#else
extern uint64_t xbg_desired_present_time_ns(void) __attribute__((weak));
#endif
static uint64_t desired;
#ifdef WITH_ENGINE
uint64_t xbg_desired_present_time_ns(void) { return desired; }
#endif
''' + marker + '\n' + schedule + r'''
int main(int argc, char **argv) {
    assert(argc==2);
    unsetenv("FFRS_APP_FILES_DIR");assert(!nvn_vulkan_present_timing_requested());
    setenv("FFRS_APP_FILES_DIR",argv[1],1);assert(!nvn_vulkan_present_timing_requested());
    char path[PATH_MAX];snprintf(path,sizeof(path),"%s/gfx-present-timing",argv[1]);
    FILE *file=fopen(path,"wb");assert(file);fputs("0",file);fclose(file);
    assert(!nvn_vulkan_present_timing_requested());
    file=fopen(path,"wb");assert(file);fputs("1",file);fclose(file);
    assert(nvn_vulkan_present_timing_requested());
    setenv("FFRS_APP_FILES_DIR","",1);assert(!nvn_vulkan_present_timing_requested());
    char long_path[PATH_MAX+1];for(unsigned i=0;i<PATH_MAX;++i)long_path[i]='a';long_path[PATH_MAX]=0;
    setenv("FFRS_APP_FILES_DIR",long_path,1);assert(!nvn_vulkan_present_timing_requested());
    int old_next=7,semaphore=8,swapchain=9,index=10;
    VkPresentInfoKHR info={&old_next,1,&semaphore,1,&swapchain,&index};
    VkPresentTimesInfoGOOGLE timing={0};VkPresentTimeGOOGLE time={0};
    nvn_vulkan_state state={0,0};desired=1000000000;
    nvn_vulkan_schedule_present(&state,&info,&timing,&time);
    assert(info.pNext==&old_next && state.present_timing_id==0);
    state.present_timing_active=1;desired=0;
    nvn_vulkan_schedule_present(&state,&info,&timing,&time);
    assert(info.pNext==&old_next && state.present_timing_id==0);
    desired=1000000000;
    nvn_vulkan_schedule_present(&state,&info,&timing,&time);
#ifdef WITH_ENGINE
    assert(info.pNext==&timing && timing.pNext==&old_next);
    assert(timing.sType==VK_STRUCTURE_TYPE_PRESENT_TIMES_INFO_GOOGLE && timing.swapchainCount==1 && timing.pTimes==&time);
    assert(time.presentID==1 && time.desiredPresentTime==desired);
    assert(info.waitSemaphoreCount==1 && info.pWaitSemaphores==&semaphore);
    assert(info.swapchainCount==1 && info.pSwapchains==&swapchain && info.pImageIndices==&index);
    info.pNext=&old_next;state.present_timing_id=UINT32_MAX;
    nvn_vulkan_schedule_present(&state,&info,&timing,&time);
    assert(time.presentID==1 && state.present_timing_id==1);
#else
    assert(info.pNext==&old_next && state.present_timing_id==0);
#endif
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'timing.c'
            code.write_text(program)
            for engine in (False, True):
                own = path / ('engine' if engine else 'standalone')
                own.mkdir()
                executable = path / ('test-engine' if engine else 'test-standalone')
                command = [shutil.which('clang') or 'cc', '-std=c11',
                           '-D_POSIX_C_SOURCE=200809L', '-fsanitize=address,undefined']
                if engine:
                    command.append('-DWITH_ENGINE')
                elif sys.platform == 'darwin':
                    command.append('-Wl,-U,_xbg_desired_present_time_ns')
                compiled = subprocess.run(command + [str(code), '-o', str(executable)],
                                          capture_output=True, text=True)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                run = subprocess.run([str(executable), str(own)], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)

    def test_device_swapchain_and_both_present_entry_points_are_wired(self):
        source = SOURCE.read_text()
        self.assertIn('extern uint64_t xbg_desired_present_time_ns(void) __attribute__((weak));', source)
        self.assertEqual(source.count('nvn_vulkan_schedule_present(st, &present_info, &timing, &time);'), 2)
        self.assertEqual(source.count('result = vkQueuePresentKHR(st->queue, &present_info);'), 2)
        self.assertIn('st->present_timing_active = st->display_timing_enabled && present_mode == VK_PRESENT_MODE_FIFO_KHR;', source)
        self.assertIn('st->swapchain_supported && display_timing_supported &&\n        xbg_desired_present_time_ns && nvn_vulkan_present_timing_requested()', source)
        begin = source.index('if (result != VK_SUCCESS && st->display_timing_enabled)')
        end = source.index('/* vkCreateDevice succeeded', begin)
        self.assertIn('--device_info.enabledExtensionCount;', source[begin:end])
        self.assertIn('st->display_timing_enabled = 0;', source[begin:end])
        self.assertIn('vkCreateDevice(st->physical, &device_info, NULL, &st->device);', source[begin:end])

    def test_actual_device_extension_negotiation_and_failure_fallback(self):
        source = SOURCE.read_text()
        begin = source.index('    const char *device_extensions[3];')
        end = source.index('    /* vkCreateDevice succeeded', begin)
        program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int VkBool32;
typedef int VkResult;
#define VK_FALSE 0
#define VK_TRUE 1
#define VK_SUCCESS 0
#define VK_NULL_HANDLE 0
#define VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FAULT_FEATURES_EXT 1
#define VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2 2
#define VK_KHR_SWAPCHAIN_EXTENSION_NAME "VK_KHR_swapchain"
#define VK_EXT_DEVICE_FAULT_EXTENSION_NAME "VK_EXT_device_fault"
#define VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME "VK_GOOGLE_display_timing"
typedef struct { int sType;void *pNext;int deviceFaultVendorBinary,deviceFault; } VkPhysicalDeviceFaultFeaturesEXT;
typedef struct { int sType;void *pNext; } VkPhysicalDeviceFeatures2;
typedef struct { char extensionName[256]; } VkExtensionProperties;
typedef struct { unsigned enabledExtensionCount;const char *const *ppEnabledExtensionNames;const void *pNext; } DeviceInfo;
typedef struct { unsigned physical,swapchain_supported,display_timing_enabled,device,instance; } State;
static unsigned supported_mask,marker,create_calls,fail_first,fail_all,destroyed;
static int old_feature_chain;
static uint64_t xbg_desired_present_time_ns(void) { return 1; }
static int nvn_vulkan_present_timing_requested(void) { return marker; }
static VkResult vkEnumerateDeviceExtensionProperties(unsigned physical,void *layer,unsigned *count,VkExtensionProperties *out) {
    (void)physical;(void)layer;
    const char *names[]={VK_KHR_SWAPCHAIN_EXTENSION_NAME,VK_EXT_DEVICE_FAULT_EXTENSION_NAME,VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME};
    unsigned n=0;for(unsigned i=0;i<3;++i)if(supported_mask&(1u<<i)){if(out)strcpy(out[n].extensionName,names[i]);++n;}
    *count=n;return VK_SUCCESS;
}
static void vkGetPhysicalDeviceFeatures2(unsigned physical,VkPhysicalDeviceFeatures2 *features) {
    (void)physical;((VkPhysicalDeviceFaultFeaturesEXT *)features->pNext)->deviceFault=1;
}
static VkResult vkCreateDevice(unsigned physical,const DeviceInfo *info,void *allocator,unsigned *device) {
    (void)physical;(void)allocator;++create_calls;
    unsigned expected=((supported_mask&1)!=0)+((supported_mask&2)!=0);
    int timing=(supported_mask&5)==5 && marker && create_calls==1;
    assert(info->enabledExtensionCount==expected+(unsigned)timing);
    unsigned index=0;
    if(supported_mask&1)assert(!strcmp(info->ppEnabledExtensionNames[index++],VK_KHR_SWAPCHAIN_EXTENSION_NAME));
    if(supported_mask&2){
        assert(!strcmp(info->ppEnabledExtensionNames[index++],VK_EXT_DEVICE_FAULT_EXTENSION_NAME));
        const VkPhysicalDeviceFaultFeaturesEXT *fault=info->pNext;
        assert(fault->deviceFault && fault->pNext==&old_feature_chain);
    }else assert(info->pNext==&old_feature_chain);
    if(timing)assert(!strcmp(info->ppEnabledExtensionNames[index],VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME));
    if(fail_all || (fail_first && create_calls==1))return -7;
    *device=19;return VK_SUCCESS;
}
static void vkDestroyInstance(unsigned instance,void *allocator) { (void)instance;(void)allocator;++destroyed; }
static int negotiate(State *st) {
    DeviceInfo device_info={0};device_info.pNext=&old_feature_chain;
    VkResult result;
    unsigned core12_route=0;
    struct { unsigned shaderOutputLayer,shaderOutputViewportIndex; } supported12={0},requested12={0};
''' + source[begin:end] + r'''
    return 1;
}
int main(void) {
    for(supported_mask=0;supported_mask<8;++supported_mask)for(marker=0;marker<2;++marker) {
        for(unsigned failure=0;failure<3;++failure) {
            fail_first=failure==1;fail_all=failure==2;create_calls=destroyed=0;
            State *state=calloc(1,sizeof(*state));assert(state);state->physical=1;state->instance=2;
            int eligible=(supported_mask&5)==5 && marker;
            int ok=negotiate(state);
            assert(create_calls==(eligible && failure ? 2u:1u));
            assert(ok==(!failure || (failure==1 && eligible)));
            if(ok){assert(state->device==19);assert(state->display_timing_enabled==(unsigned)(eligible && !failure));assert(!destroyed);free(state);}
            else assert(destroyed==1);
        }
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'device.c'
            code.write_text(program)
            executable = path / 'device'
            compiled = subprocess.run([shutil.which('clang') or 'cc', '-std=c11',
                                       '-fsanitize=address,undefined', str(code),
                                       '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
