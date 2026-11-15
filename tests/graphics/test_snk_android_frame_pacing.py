import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'src/android/native/android_frame_pacing.cpp'

JNI_HEADER = r'''
#pragma once
using jint = int;
using jboolean = unsigned char;
using jobject = void *;
using jclass = void *;
#define JNIEXPORT
#define JNICALL
#define JNI_OK 0
#define JNI_EDETACHED -2
#define JNI_VERSION_1_6 0x10006
struct JNIEnv;
struct JavaVM {
    jint GetEnv(void **env, jint version);
    jint AttachCurrentThread(JNIEnv **env, void *);
    jint DetachCurrentThread();
};
struct JNIEnv {
    jobject NewLocalRef(jobject object);
    jobject NewGlobalRef(jobject object);
    void DeleteLocalRef(jobject object);
    void DeleteGlobalRef(jobject object);
    bool ExceptionCheck();
    void ExceptionClear();
    bool IsSameObject(jobject first, jobject second);
    jint GetJavaVM(JavaVM **vm);
};
'''

VULKAN_HEADER = r'''
#pragma once
#include <cstdint>
using VkDevice = uint64_t;
using VkQueue = uint64_t;
using VkPhysicalDevice = uint64_t;
using VkSwapchainKHR = uint64_t;
using VkResult = int;
using VkPresentModeKHR = int;
#define VK_NULL_HANDLE 0
#define VK_SUCCESS 0
#define VK_ERROR_INITIALIZATION_FAILED -3
#define VK_PRESENT_MODE_FIFO_KHR 2
#define VK_MAX_EXTENSION_NAME_SIZE 256
struct VkExtensionProperties { char extensionName[256]; };
struct VkDeviceCreateInfo {
    const void *pNext;
    uint32_t enabledExtensionCount;
    const char *const *ppEnabledExtensionNames;
};
struct VkPresentInfoKHR {
    uint32_t swapchainCount;
    const VkSwapchainKHR *pSwapchains;
};
VkResult vkCreateDevice(VkPhysicalDevice physical, const VkDeviceCreateInfo *info,
    const void *allocator, VkDevice *device);
VkResult vkEnumerateDeviceExtensionProperties(VkPhysicalDevice physical,
    const char *layer, uint32_t *count, VkExtensionProperties *properties);
VkResult vkQueuePresentKHR(VkQueue queue, const VkPresentInfoKHR *info);
'''

SWAPPY_HEADER = r'''
#pragma once
#include <jni.h>
#include <vulkan/vulkan.h>
struct ANativeWindow {};
void SwappyVk_determineDeviceExtensions(VkPhysicalDevice, uint32_t,
    VkExtensionProperties *, uint32_t *, char **);
void SwappyVk_setQueueFamilyIndex(VkDevice, VkQueue, uint32_t);
bool SwappyVk_initAndGetRefreshCycleDuration(JNIEnv *, jobject, VkPhysicalDevice,
    VkDevice, VkSwapchainKHR, uint64_t *);
void SwappyVk_setWindow(VkDevice, VkSwapchainKHR, ANativeWindow *);
void SwappyVk_setAutoSwapInterval(bool);
void SwappyVk_setAutoPipelineMode(bool);
void SwappyVk_enableStats(VkSwapchainKHR, bool);
void SwappyVk_setSwapIntervalNS(VkDevice, VkSwapchainKHR, uint64_t);
bool SwappyVk_isEnabled(VkSwapchainKHR, bool *);
void SwappyVk_enableFramePacing(VkSwapchainKHR, bool);
void SwappyVk_enableBlockingWait(VkSwapchainKHR, bool);
VkResult SwappyVk_queuePresent(VkQueue, const VkPresentInfoKHR *);
void SwappyVk_destroySwapchain(VkDevice, VkSwapchainKHR);
void SwappyVk_destroyDevice(VkDevice);
'''

HARNESS = r'''
#include <jni.h>
#include <swappy/swappyVk.h>
#include "nvn_android_frame_pacing.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

static JavaVM vm;
static JNIEnv env;
static bool thread_attached = false;
static bool attach_fails = false;
static bool local_ref_fails = false;
static bool pending_exception = false;
static unsigned attachments, detachments, globals, locals;
jint JavaVM::GetEnv(void **result, jint) {
    *result = &env;
    return thread_attached ? JNI_OK : JNI_EDETACHED;
}
jint JavaVM::AttachCurrentThread(JNIEnv **result, void *) {
    if (attach_fails) return -1;
    ++attachments;
    thread_attached = true;
    *result = &env;
    return JNI_OK;
}
jint JavaVM::DetachCurrentThread() {
    ++detachments;
    thread_attached = false;
    return JNI_OK;
}
jobject JNIEnv::NewLocalRef(jobject object) {
    if (local_ref_fails) { pending_exception = true; return nullptr; }
    ++locals;
    return object;
}
jobject JNIEnv::NewGlobalRef(jobject object) { ++globals; return object; }
void JNIEnv::DeleteLocalRef(jobject) { assert(locals); --locals; }
void JNIEnv::DeleteGlobalRef(jobject) { assert(globals); --globals; }
bool JNIEnv::ExceptionCheck() { return pending_exception; }
void JNIEnv::ExceptionClear() { pending_exception = false; }
bool JNIEnv::IsSameObject(jobject first, jobject second) { return first == second; }
jint JNIEnv::GetJavaVM(JavaVM **result) { *result = &vm; return JNI_OK; }

static bool fail_extra_extensions = false;
static bool fail_enumeration = false;
static bool fail_init = false;
static bool fail_init_exception = false;
static bool sdk_enabled = true;
static unsigned device_calls, sdk_creates, sdk_destroys, queue_calls;
static unsigned paced_presents, original_presents, swapchain_destroys;
static unsigned last_extension_count;
static uint64_t interval;
static const void *feature_chain = reinterpret_cast<void *>(81);
VkResult vkCreateDevice(VkPhysicalDevice, const VkDeviceCreateInfo *info,
    const void *, VkDevice *device) {
    ++device_calls;
    assert(info->pNext == feature_chain);
    assert(!strcmp(info->ppEnabledExtensionNames[0], "VK_KHR_swapchain"));
    last_extension_count = info->enabledExtensionCount;
    if (fail_extra_extensions && last_extension_count > 1)
        return VK_ERROR_INITIALIZATION_FAILED;
    if (last_extension_count > 1)
        assert(!strcmp(info->ppEnabledExtensionNames[1], "VK_GOOGLE_display_timing"));
    *device = 17;
    return VK_SUCCESS;
}
VkResult vkEnumerateDeviceExtensionProperties(VkPhysicalDevice, const char *,
    uint32_t *count, VkExtensionProperties *properties) {
    if (fail_enumeration) return VK_ERROR_INITIALIZATION_FAILED;
    *count = 1;
    if (properties) strcpy(properties[0].extensionName, "VK_GOOGLE_display_timing");
    return VK_SUCCESS;
}
VkResult vkQueuePresentKHR(VkQueue, const VkPresentInfoKHR *) {
    ++original_presents;
    return 7;
}
void SwappyVk_determineDeviceExtensions(VkPhysicalDevice, uint32_t,
    VkExtensionProperties *, uint32_t *count, char **names) {
    *count = 2;
    if (names) {
        strcpy(names[0], "VK_KHR_swapchain");
        strcpy(names[1], "VK_GOOGLE_display_timing");
    }
}
void SwappyVk_setQueueFamilyIndex(VkDevice device, VkQueue queue, uint32_t family) {
    assert(device == 17 && queue == 23 && family == 4);
    ++queue_calls;
}
bool SwappyVk_initAndGetRefreshCycleDuration(JNIEnv *context, jobject owner,
    VkPhysicalDevice, VkDevice, VkSwapchainKHR, uint64_t *refresh) {
    assert(context == &env && owner && thread_attached);
    ++sdk_creates;
    *refresh = 16666667;
    if (fail_init_exception) pending_exception = true;
    return !fail_init;
}
void SwappyVk_setWindow(VkDevice, VkSwapchainKHR, ANativeWindow *window) { assert(window); }
void SwappyVk_setAutoSwapInterval(bool value) { assert(!value); }
void SwappyVk_setAutoPipelineMode(bool value) { assert(!value); }
void SwappyVk_enableStats(VkSwapchainKHR, bool value) { assert(!value); }
void SwappyVk_setSwapIntervalNS(VkDevice, VkSwapchainKHR, uint64_t value) { interval = value; }
bool SwappyVk_isEnabled(VkSwapchainKHR, bool *value) { *value = sdk_enabled; return true; }
void SwappyVk_enableFramePacing(VkSwapchainKHR, bool value) { sdk_enabled = value; }
void SwappyVk_enableBlockingWait(VkSwapchainKHR, bool) {}
VkResult SwappyVk_queuePresent(VkQueue, const VkPresentInfoKHR *) {
    ++paced_presents;
    return 11;
}
void SwappyVk_destroySwapchain(VkDevice, VkSwapchainKHR) { ++swapchain_destroys; }
void SwappyVk_destroyDevice(VkDevice) { ++sdk_destroys; }

extern "C" void Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(
    JNIEnv *, jclass, jobject, jboolean);
int main(int argc, char **argv) {
    assert(argc == 2);
    const char *extensions[] = {"VK_KHR_swapchain"};
    VkDeviceCreateInfo info{feature_chain, 1, extensions};
    VkDevice device;
    VkSwapchainKHR swapchain = 29;
    VkPresentInfoKHR present{1, &swapchain};
    auto owner = reinterpret_cast<jobject>(1);
    auto other = reinterpret_cast<jobject>(2);
    unsetenv("FFRS_APP_FILES_DIR");
    assert(nvn_android_pacing_create_device(5, &info, &device) == VK_SUCCESS);
    assert(last_extension_count == 1 && attachments == 0);
    setenv("FFRS_APP_FILES_DIR", argv[1], 1);
    assert(nvn_android_pacing_create_device(5, &info, &device) == VK_SUCCESS);
    assert(last_extension_count == 1); // Missing Activity falls back.
    Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(&env, nullptr, owner, true);
    assert(globals == 1);
    attach_fails = true;
    assert(nvn_android_pacing_create_device(5, &info, &device) == VK_SUCCESS);
    assert(last_extension_count == 1);
    attach_fails = false;
    local_ref_fails = true;
    assert(nvn_android_pacing_create_device(5, &info, &device) == VK_SUCCESS);
    assert(last_extension_count == 1 && !pending_exception);
    local_ref_fails = false;
    fail_enumeration = true;
    assert(nvn_android_pacing_create_device(5, &info, &device) == VK_SUCCESS);
    assert(last_extension_count == 1);
    fail_enumeration = false;
    fail_extra_extensions = true;
    unsigned before = device_calls;
    assert(nvn_android_pacing_create_device(5, &info, &device) == VK_SUCCESS);
    assert(device_calls == before + 2 && last_extension_count == 1);
    nvn_android_pacing_queue(device, 23, 4);
    assert(queue_calls == 0 && !nvn_android_pacing_target(33333333));
    assert(nvn_android_pacing_present(23, &present) == 7);
    fail_extra_extensions = false;
    assert(nvn_android_pacing_create_device(5, &info, &device) == VK_SUCCESS);
    assert(last_extension_count == 2);
    nvn_android_pacing_queue(device, 23, 4);
    nvn_android_pacing_swapchain(5, device, swapchain, owner, 1);
    assert(sdk_creates == 0); // MAILBOX retains software pacing.
    fail_init = true;
    nvn_android_pacing_swapchain(5, device, swapchain, owner, VK_PRESENT_MODE_FIFO_KHR);
    assert(!nvn_android_pacing_target(33333333));
    assert(nvn_android_pacing_present(23, &present) == 7);
    fail_init = false;
    fail_init_exception = true;
    nvn_android_pacing_swapchain(5, device, swapchain, owner, VK_PRESENT_MODE_FIFO_KHR);
    assert(!pending_exception && !nvn_android_pacing_target(33333333));
    fail_init_exception = false;
    nvn_android_pacing_swapchain(5, device, swapchain, owner, VK_PRESENT_MODE_FIFO_KHR);
    assert(nvn_android_pacing_target(33333333) && interval == 33333333);
    assert(nvn_android_pacing_present(23, &present) == 11);
    assert(nvn_android_pacing_present(24, &present) == 7);
    assert(!nvn_android_pacing_target(0));
    assert(nvn_android_pacing_target(16666666) && interval == 16666666);
    nvn_android_pacing_destroy_swapchain(device, 31);
    assert(nvn_android_pacing_target(16666666));
    nvn_android_pacing_destroy_swapchain(device, swapchain);
    assert(!nvn_android_pacing_target(16666666));
    assert(nvn_android_pacing_present(23, &present) == 7);
    nvn_android_pacing_swapchain(5, device, swapchain, owner, VK_PRESENT_MODE_FIFO_KHR);
    assert(nvn_android_pacing_target(33333333));
    nvn_android_pacing_destroy_device(device);
    assert(sdk_destroys == 1 && swapchain_destroys == 4);
    assert(!nvn_android_pacing_target(33333333));
    Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(&env, nullptr, other, true);
    Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(&env, nullptr, owner, false);
    assert(globals == 1); // An old Activity cannot detach its replacement.
    Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(&env, nullptr, other, false);
    assert(globals == 0 && locals == 0 && attachments == detachments);
    assert(paced_presents == 1 && original_presents == 4);
}
'''


class AndroidFramePacingTests(unittest.TestCase):
    def test_actual_wrapper_fallback_lifecycle_and_target_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'vulkan').mkdir()
            (path / 'swappy').mkdir()
            (path / 'jni.h').write_text(JNI_HEADER)
            (path / 'vulkan/vulkan.h').write_text(VULKAN_HEADER)
            (path / 'swappy/swappyVk.h').write_text(SWAPPY_HEADER)
            (path / 'gfx-frame-pacing').write_text('1')
            harness = path / 'harness.cpp'
            harness.write_text(HARNESS)
            executable = path / 'pacing'
            compiler = shutil.which('clang++') or 'c++'
            subprocess.run([
                compiler, '-std=c++17', '-DSNK_HAVE_SWAPPY=1',
                '-fsanitize=address,undefined', '-I', str(path),
                '-I', str(ROOT / 'src/graphics/nvn_device'),
                str(harness), str(SOURCE), '-o', str(executable),
            ], check=True, capture_output=True)
            result = subprocess.run([str(executable), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # A regular build keeps the JNI entry point without an SDK dependency.
            harness.write_text(r'''
#include <jni.h>
extern "C" void Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(
    JNIEnv *, jclass, jobject, jboolean);
int main() {
    Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(nullptr, nullptr, nullptr, false);
}
''')
            subprocess.run([
                compiler, '-std=c++17', '-I', str(path), str(harness),
                str(SOURCE), '-o', str(executable),
            ], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
