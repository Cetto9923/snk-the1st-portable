package org.snk.the1st;
public class DeviceProfileContract {
    private static void check(String soc, int widthDp, String override, String id, int edge, int fps) {
        DeviceProfile p = DeviceProfile.select(soc, widthDp, override);
        if (!p.id.equals(id) || p.targetShortEdge != edge || p.targetFps != fps)
            throw new AssertionError(soc + ": " + p.id);
        if (p.nativeRenderHeight() != (edge <= 720 ? edge : 0))
            throw new AssertionError("native render height " + soc);
    }
    public static void main(String[] args) {
        check("SM8635", 768, "", "tablet_sd8s", 1080, 30);
        check("MT6897", 420, "", "phone_mali", 720, 30);
        check(null, 0, null, "handheld_mid", 720, 30);
        check("SM8635", 768, "handheld_mid", "handheld_mid", 540, 30);
        check("MT6897", 420, "odin_elite", "odin_elite", 1080, 30);
        check("SM8635", 768, "invalid", "tablet_sd8s", 1080, 30);
        check("SM8635", 420, "", "phone_adreno", 1080, 30);
        check("SM86350", 768, "", "handheld_mid", 720, 30);
        check("SM8635", 0, "", "phone_adreno", 1080, 30);
        check("SM8635", 420, "tablet_sd8s", "tablet_sd8s", 1080, 30);
        DeviceProfile rg = DeviceProfile.select("MT6897", "RG477M", 768, "");
        if (!rg.id.equals("handheld_mid") || rg.targetShortEdge != 540 || rg.targetFps != 30)
            throw new AssertionError("RG477M profile");
        for (String chip : new String[]{"SM8450", "SM8475", "SM8550", "SM8650", "SM8750", "SM8850",
                "SM8950", "Qualcomm Technologies, Inc SM8750-AB", "Snapdragon 8 Gen 3", "Snapdragon 8 Elite"})
            check(chip, 420, "", "phone_adreno", 1080, 30);
        for (String chip : new String[]{"MT6983", "MT6985", "MT6989", "MT6991", "MT6993",
                "MediaTek MT6993", "Dimensity 9000", "Dimensity 9200+", "Dimensity 9300", "Dimensity 9400", "Dimensity 9500"})
            check(chip, 420, "", "phone_mali_high", 1080, 30);
        check("SM88500", 420, "", "handheld_mid", 720, 30);
        check("SM7675", 420, "", "handheld_mid", 720, 30);
        check("Dimensity 8400", 420, "", "phone_mali", 720, 30);
        DeviceProfile small = DeviceProfile.select("SM8750", "Test", 420, 720, "");
        if (small.targetShortEdge != 720 || small.targetFps != 30)
            throw new AssertionError("physical screen limit");
        if (DeviceProfile.formFactorWidthDp(1600, 2560, 320, 400) != 800
                || DeviceProfile.formFactorWidthDp(0, 0, 0, 420) != 420)
            throw new AssertionError("physical form factor");
        System.out.println("profile selection checks passed; runtime rendering not covered");
    }
}
