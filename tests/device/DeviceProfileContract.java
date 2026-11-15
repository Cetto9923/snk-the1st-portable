package org.snk.the1st;
public class DeviceProfileContract {
    private static void check(String soc, int widthDp, String override, String id, int edge, int fps) {
        DeviceProfile p = DeviceProfile.select(soc, widthDp, override);
        if (!p.id.equals(id) || p.targetShortEdge != edge || p.targetFps != fps)
            throw new AssertionError(soc + ": " + p.id);
    }
    public static void main(String[] args) {
        check("SM8635", 768, "", "tablet_sd8s", 1080, 30);
        check("MT6897", 420, "", "phone_mali", 720, 30);
        check(null, 0, null, "handheld_mid", 720, 30);
        check("SM8635", 768, "handheld_mid", "handheld_mid", 720, 30);
        check("MT6897", 420, "odin_elite", "odin_elite", 1080, 30);
        check("SM8635", 768, "invalid", "tablet_sd8s", 1080, 30);
        check("SM8635", 420, "", "handheld_mid", 720, 30);
        check("SM86350", 768, "", "handheld_mid", 720, 30);
        check("SM8635", 0, "", "handheld_mid", 720, 30);
        check("SM8635", 420, "tablet_sd8s", "tablet_sd8s", 1080, 30);
        DeviceProfile rg = DeviceProfile.select("MT6897", "RG477M", 768, "");
        if (!rg.id.equals("handheld_mid") || rg.targetShortEdge != 720 || rg.targetFps != 30)
            throw new AssertionError("RG477M profile");
        check("MT6989", 420, "", "phone_mali", 720, 30);
        check("Dimensity 9400", 420, "", "phone_mali", 720, 30);
        if (DeviceProfile.formFactorWidthDp(1600, 2560, 320, 400) != 800
                || DeviceProfile.formFactorWidthDp(0, 0, 0, 420) != 420)
            throw new AssertionError("physical form factor");
        System.out.println("profile selection checks passed; runtime rendering not covered");
    }
}
