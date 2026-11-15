#include <jni.h>

#ifdef SNK_HAVE_SWAPPY
#include "../../graphics/nvn_device/nvn_android_frame_pacing.h"
#include <swappy/swappyVk.h>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

namespace {
std::mutex activity_mutex;
JavaVM *java_vm = nullptr;
jobject activity = nullptr;

/* Only the render hooks call Swappy. The UI reference lock is separate so
 * Activity teardown never waits for the render queue while holding it. */
std::mutex pacing_mutex;
VkDevice pacing_device = VK_NULL_HANDLE;
VkQueue pacing_queue = VK_NULL_HANDLE;
VkSwapchainKHR pacing_swapchain = VK_NULL_HANDLE;
uint64_t target_interval_ns = 33333333;
bool pacing_enabled = false;

bool requested() {
    const char *directory = getenv("FFRS_APP_FILES_DIR");
    if (!directory || !directory[0]) return false;
    const std::string path = std::string(directory) + "/gfx-frame-pacing";
    FILE *file = fopen(path.c_str(), "rb");
    if (!file) return false;
    int value = fgetc(file);
    fclose(file);
    return value == '1';
}

/* A local reference keeps an Activity alive if its global reference is
 * released or replaced during native initialization. */
struct ActivityReference {
    JavaVM *vm = nullptr;
    JNIEnv *env = nullptr;
    jobject object = nullptr;
    bool attached = false;

    ActivityReference() {
        std::lock_guard<std::mutex> lock(activity_mutex);
        vm = java_vm;
        if (!vm || !activity) return;
        jint status = vm->GetEnv(reinterpret_cast<void **>(&env), JNI_VERSION_1_6);
        if (status == JNI_EDETACHED) {
            if (vm->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
            attached = true;
        } else if (status != JNI_OK) {
            env = nullptr;
            return;
        }
        object = env->NewLocalRef(activity);
        if (env->ExceptionCheck()) {
            env->ExceptionClear();
            object = nullptr;
        }
    }

    ~ActivityReference() {
        if (object) env->DeleteLocalRef(object);
        if (attached) vm->DetachCurrentThread();
    }
};
}

extern "C" VkResult nvn_android_pacing_create_device(VkPhysicalDevice physical,
    const VkDeviceCreateInfo *info, VkDevice *device) {
    std::lock_guard<std::mutex> lock(pacing_mutex);
    if (pacing_device || !requested()) return vkCreateDevice(physical, info, nullptr, device);
    ActivityReference reference;
    if (!reference.object) return vkCreateDevice(physical, info, nullptr, device);

    uint32_t available_count = 0;
    if (vkEnumerateDeviceExtensionProperties(physical, nullptr, &available_count, nullptr) != VK_SUCCESS)
        return vkCreateDevice(physical, info, nullptr, device);
    std::vector<VkExtensionProperties> available(available_count);
    if (vkEnumerateDeviceExtensionProperties(physical, nullptr, &available_count, available.data()) != VK_SUCCESS)
        return vkCreateDevice(physical, info, nullptr, device);
    uint32_t required_count = 0;
    SwappyVk_determineDeviceExtensions(physical, available_count, available.data(), &required_count, nullptr);
    std::vector<std::array<char, VK_MAX_EXTENSION_NAME_SIZE>> names(required_count);
    std::vector<char *> required(required_count);
    for (uint32_t i = 0; i < required_count; ++i) required[i] = names[i].data();
    if (required_count)
        SwappyVk_determineDeviceExtensions(physical, available_count, available.data(), &required_count, required.data());
    std::vector<const char *> extensions;
    for (uint32_t i = 0; i < info->enabledExtensionCount; ++i)
        extensions.push_back(info->ppEnabledExtensionNames[i]);
    for (const char *name : required) {
        bool duplicate = false;
        for (const char *existing : extensions) duplicate |= strcmp(name, existing) == 0;
        if (!duplicate) extensions.push_back(name);
    }
    VkDeviceCreateInfo paced = *info;
    paced.enabledExtensionCount = static_cast<uint32_t>(extensions.size());
    paced.ppEnabledExtensionNames = extensions.data();
    VkResult result = vkCreateDevice(physical, &paced, nullptr, device);
    if (result == VK_SUCCESS) {
        pacing_device = *device;
        fprintf(stderr, "[snk-pacing] device ready, SDK extensions=%u\n", required_count);
        return result;
    }
    fprintf(stderr, "[snk-pacing] device setup failed %d, using original extensions\n", result);
    return vkCreateDevice(physical, info, nullptr, device);
}

extern "C" void nvn_android_pacing_queue(VkDevice device, VkQueue queue, uint32_t family) {
    std::lock_guard<std::mutex> lock(pacing_mutex);
    if (device != pacing_device) return;
    pacing_queue = queue;
    SwappyVk_setQueueFamilyIndex(device, queue, family);
}

extern "C" void nvn_android_pacing_swapchain(VkPhysicalDevice physical, VkDevice device,
    VkSwapchainKHR swapchain, void *window, VkPresentModeKHR mode) {
    std::lock_guard<std::mutex> lock(pacing_mutex);
    if (device != pacing_device || mode != VK_PRESENT_MODE_FIFO_KHR) return;
    ActivityReference reference;
    if (!reference.object) return;
    uint64_t refresh_ns = 0;
    bool initialized = SwappyVk_initAndGetRefreshCycleDuration(reference.env, reference.object,
        physical, device, swapchain, &refresh_ns);
    if (reference.env->ExceptionCheck()) {
        reference.env->ExceptionClear();
        initialized = false;
    }
    if (!initialized) {
        SwappyVk_destroySwapchain(device, swapchain);
        fprintf(stderr, "[snk-pacing] initialization failed, using software pacing\n");
        return;
    }
    pacing_swapchain = swapchain;
    SwappyVk_setWindow(device, swapchain, static_cast<ANativeWindow *>(window));
    SwappyVk_setAutoSwapInterval(false);
    SwappyVk_setAutoPipelineMode(false);
    SwappyVk_enableStats(swapchain, false);
    SwappyVk_setSwapIntervalNS(device, swapchain, target_interval_ns ? target_interval_ns : 33333333);
    bool enabled = false;
    pacing_enabled = SwappyVk_isEnabled(swapchain, &enabled) && enabled;
    if (!target_interval_ns) {
        SwappyVk_enableFramePacing(swapchain, false);
        SwappyVk_enableBlockingWait(swapchain, false);
        pacing_enabled = false;
    }
    fprintf(stderr, "[snk-pacing] swapchain initialized, enabled=%d refresh_ns=%llu target_ns=%llu\n",
        pacing_enabled, static_cast<unsigned long long>(refresh_ns),
        static_cast<unsigned long long>(target_interval_ns));
}

extern "C" int nvn_android_pacing_target(uint64_t interval_ns) {
    std::lock_guard<std::mutex> lock(pacing_mutex);
    if (!pacing_swapchain) return 0;
    if (target_interval_ns != interval_ns) {
        target_interval_ns = interval_ns;
        SwappyVk_enableFramePacing(pacing_swapchain, interval_ns != 0);
        SwappyVk_enableBlockingWait(pacing_swapchain, interval_ns != 0);
        if (interval_ns) SwappyVk_setSwapIntervalNS(pacing_device, pacing_swapchain, interval_ns);
        bool enabled = false;
        pacing_enabled = interval_ns && SwappyVk_isEnabled(pacing_swapchain, &enabled) && enabled;
    }
    return pacing_enabled;
}

extern "C" VkResult nvn_android_pacing_present(VkQueue queue, const VkPresentInfoKHR *info) {
    std::lock_guard<std::mutex> lock(pacing_mutex);
    if (pacing_swapchain && queue == pacing_queue && info->swapchainCount == 1 &&
        info->pSwapchains[0] == pacing_swapchain)
        return SwappyVk_queuePresent(queue, info);
    return vkQueuePresentKHR(queue, info);
}

extern "C" void nvn_android_pacing_destroy_swapchain(VkDevice device, VkSwapchainKHR swapchain) {
    std::lock_guard<std::mutex> lock(pacing_mutex);
    if (device != pacing_device || !pacing_swapchain || swapchain != pacing_swapchain) return;
    SwappyVk_destroySwapchain(device, swapchain);
    pacing_swapchain = VK_NULL_HANDLE;
    pacing_enabled = false;
}

extern "C" void nvn_android_pacing_destroy_device(VkDevice device) {
    std::lock_guard<std::mutex> lock(pacing_mutex);
    if (device != pacing_device) return;
    if (pacing_swapchain) SwappyVk_destroySwapchain(device, pacing_swapchain);
    SwappyVk_destroyDevice(device);
    pacing_swapchain = VK_NULL_HANDLE;
    pacing_device = VK_NULL_HANDLE;
    pacing_queue = VK_NULL_HANDLE;
    pacing_enabled = false;
}
#endif

extern "C" JNIEXPORT void JNICALL
Java_org_snk_the1st_GameWindowNative_setFramePacingActivity(JNIEnv *env, jclass,
    jobject owner, jboolean attached) {
#ifdef SNK_HAVE_SWAPPY
    std::lock_guard<std::mutex> lock(activity_mutex);
    if (!attached) {
        if (activity && env->IsSameObject(activity, owner)) {
            env->DeleteGlobalRef(activity);
            activity = nullptr;
        }
        return;
    }
    jobject replacement = env->NewGlobalRef(owner);
    if (!replacement) return;
    env->GetJavaVM(&java_vm);
    if (activity) env->DeleteGlobalRef(activity);
    activity = replacement;
#else
    (void)env;
    (void)owner;
    (void)attached;
#endif
}
