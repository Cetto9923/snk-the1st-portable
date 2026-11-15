#ifndef NVN_ANDROID_FRAME_PACING_H
#define NVN_ANDROID_FRAME_PACING_H

#include <stdint.h>
#include <vulkan/vulkan.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Optional Android application hooks. Standalone runtime builds omit them. */
VkResult nvn_android_pacing_create_device(VkPhysicalDevice physical,
    const VkDeviceCreateInfo *info, VkDevice *device) __attribute__((weak));
void nvn_android_pacing_queue(VkDevice device, VkQueue queue,
    uint32_t family) __attribute__((weak));
void nvn_android_pacing_swapchain(VkPhysicalDevice physical, VkDevice device,
    VkSwapchainKHR swapchain, void *window, VkPresentModeKHR mode) __attribute__((weak));
int nvn_android_pacing_target(uint64_t interval_ns) __attribute__((weak));
VkResult nvn_android_pacing_present(VkQueue queue,
    const VkPresentInfoKHR *info) __attribute__((weak));
void nvn_android_pacing_destroy_swapchain(VkDevice device,
    VkSwapchainKHR swapchain) __attribute__((weak));
void nvn_android_pacing_destroy_device(VkDevice device) __attribute__((weak));

#ifdef __cplusplus
}
#endif
#endif
