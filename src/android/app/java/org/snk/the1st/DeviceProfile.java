package org.snk.the1st;

import java.util.Locale;

/** Conservative preset selection; actual rendering and present rates remain separately measured. */
final class DeviceProfile {
    final String id;
    final int targetFps;
    final int targetShortEdge;

    private DeviceProfile(String id, int targetShortEdge, int targetFps) {
        this.id = id;
        this.targetShortEdge = targetShortEdge;
        this.targetFps = targetFps;
    }

    int nativeRenderHeight() {
        // Zero preserves the game's original docked render size.
        return targetShortEdge <= 720 ? targetShortEdge : 0;
    }

    static int formFactorWidthDp(int width, int height, int densityDpi, int windowWidthDp) {
        if (width <= 0 || height <= 0 || densityDpi <= 0) return windowWidthDp;
        return (int)Math.min(Integer.MAX_VALUE, (long)Math.min(width, height) * 160 / densityDpi);
    }

    static DeviceProfile select(String soc, int smallestWidthDp, String override) {
        return select(soc, null, smallestWidthDp, override);
    }

    static DeviceProfile select(String soc, String model, int smallestWidthDp, String override) {
        return select(soc, model, smallestWidthDp, 0, override);
    }

    static DeviceProfile select(String soc, String model, int smallestWidthDp,
                                int displayShortEdge, String override) {
        String id = override == null ? "" : override.trim().toLowerCase(Locale.ROOT);
        if (id.equals("rg477m")) return new DeviceProfile(id, 450, 30);
        if (id.equals("handheld_mid")) return new DeviceProfile(id, 540, 30);
        if (id.equals("tablet_sd8s")) return new DeviceProfile(id, 1080, 30);
        if (id.equals("odin_elite")) return new DeviceProfile(id, 1080, 30);
        if (id.equals("phone_mali")) return new DeviceProfile(id, 720, 30);
        if (id.equals("phone_adreno") || id.equals("phone_mali_high"))
            return new DeviceProfile(id, 1080, 30);
        String device = model == null ? "" : model.trim().toLowerCase(Locale.ROOT);
        if (device.contains("rg477m") || device.contains("rg-477m"))
            return new DeviceProfile("rg477m", 450, 30);
        String chip = soc == null ? "" : soc.trim().toLowerCase(Locale.ROOT);
        if (chip.equals("sm8635") && smallestWidthDp >= 600)
            return new DeviceProfile("tablet_sd8s", 1080, 30);
        int phoneHeight = displayShortEdge > 0 && displayShortEdge < 1080 ? 720 : 1080;
        if (chip.matches(".*\\bsm8[0-9]{3}([^0-9].*)?") ||
                chip.matches(".*\\bsnapdragon\\s+(8\\s|8s\\s|8[0-9]{2}\\b).*"))
            return new DeviceProfile("phone_adreno", phoneHeight, 30);
        if (chip.matches(".*\\bmt69[0-9]{2}([^0-9].*)?") ||
                chip.matches(".*\\bdimensity\\s*9[0-9]{3}([^0-9].*)?"))
            return new DeviceProfile("phone_mali_high", phoneHeight, 30);
        if (chip.startsWith("mt68") || chip.startsWith("mt69") || chip.startsWith("dimensity"))
            return new DeviceProfile("phone_mali", 720, 30);
        return new DeviceProfile("handheld_mid", 720, 30);
    }
}
