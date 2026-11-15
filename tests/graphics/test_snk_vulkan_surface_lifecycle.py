import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class VulkanSurfaceLifecycleTests(unittest.TestCase):
    def test_actual_teardown_drains_gpu_and_releases_each_handle_once(self):
        source = (ROOT / 'src/graphics/nvn_device/nvn_backend_vulkan.c').read_text()
        functions = ''
        for signature in (
                'static void nvn_vulkan_destroy_window_surface(nvn_device_state *device, void *surface, void *swapchain) {',
                'static void nvn_vulkan_destroy(nvn_device_state *device) {'):
            begin = source.index(signature)
            end = begin + len(signature)
            depth = 1
            while depth:
                depth += (source[end] == '{') - (source[end] == '}')
                end += 1
            functions += source[begin:end] + '\n'
        program = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>
using VkSwapchainKHR = uintptr_t;
using VkSurfaceKHR = uintptr_t;
#define VK_NULL_HANDLE 0
struct nvn_vulkan_state { uintptr_t device, instance, swapchain, surface; };
struct nvn_device_state { void *backend_state; };
static std::vector<std::string> events;
static void vkDeviceWaitIdle(uintptr_t) { events.push_back("idle"); }
static void nvn_vulkan_release_present_path(nvn_vulkan_state *) { events.push_back("path"); }
static void vkDestroySwapchainKHR(uintptr_t, uintptr_t, void *) { events.push_back("swapchain"); }
static void vkDestroySurfaceKHR(uintptr_t, uintptr_t, void *) { events.push_back("surface"); }
static void vkDestroyDevice(uintptr_t, void *) { events.push_back("device"); }
static void vkDestroyInstance(uintptr_t, void *) { events.push_back("instance"); }
''' + functions + r'''
int main() {
    auto *state = static_cast<nvn_vulkan_state *>(malloc(sizeof(nvn_vulkan_state)));
    *state = {1, 2, 3, 4};
    nvn_device_state device{state};
    nvn_vulkan_destroy(&device);
    assert(!device.backend_state);
    assert((events == std::vector<std::string>{"idle", "path", "swapchain", "surface", "device", "instance"}));
    events.clear();
    nvn_vulkan_state window{1, 2, 3, 4};
    device.backend_state = &window;
    nvn_vulkan_destroy_window_surface(&device, nullptr, nullptr);
    assert(!window.swapchain && !window.surface);
    assert((events == std::vector<std::string>{"idle", "path", "swapchain", "surface"}));
    events.clear();
    nvn_vulkan_destroy_window_surface(&device, nullptr, nullptr);
    assert((events == std::vector<std::string>{"idle", "path"}));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'teardown.cpp'
            code.write_text(program)
            executable = path / 'teardown'
            subprocess.run([
                shutil.which('clang++') or 'c++', '-std=c++17',
                '-fsanitize=address,undefined', str(code), '-o', str(executable),
            ], check=True, capture_output=True)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        begin = source.index('static int nvn_vulkan_create_window_surface(')
        end = source.index('    create_android_surface =', begin)
        self.assertIn('nvn_vulkan_destroy_window_surface(device, NULL, NULL);', source[begin:end])
        begin = source.index('    if (!nvn_vulkan_setup_present_path(')
        end = source.index('    fprintf(stderr, "[nvn] vulkan: created a surface', begin)
        self.assertIn('nvn_vulkan_destroy_window_surface(device,', source[begin:end])
        self.assertNotIn('vkDestroySwapchainKHR', source[begin:end])


if __name__ == '__main__':
    unittest.main()
