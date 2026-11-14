#!/usr/bin/env python3
import subprocess
import time
import sys
import os
import shlex

DEVICE = "RG477M01445122"
ARTIFACT_DIR = "/Users/yuyan9923/.gemini/antigravity/brain/03910a3e-84ae-42ad-9138-7094b462b96b"

def run_adb(cmd):
    full_cmd = ["adb", "-s", DEVICE] + cmd
    return subprocess.run(full_cmd, capture_output=True, text=True)

def send_btn(bit=0, hold=220):
    cmd = ["adb", "-s", DEVICE, "shell", "am", "broadcast", "-a", "org.snk.the1st.PAD_INPUT", "--ei", "bit", str(bit), "--ei", "hold_ms", str(hold)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_pid():
    res = run_adb(["shell", "pidof", "org.snk.the1st.gamewindow"])
    return res.stdout.strip()

def capture_screen(name):
    tmp_path = f"/sdcard/{name}.png"
    local_png = os.path.join(ARTIFACT_DIR, f"{name}.png")
    local_jpg = os.path.join(ARTIFACT_DIR, f"{name}.jpg")
    run_adb(["shell", "screencap", "-p", tmp_path])
    run_adb(["pull", tmp_path, local_png])
    if os.path.exists(local_png):
        try:
            from PIL import Image
            im = Image.open(local_png)
            colors = len(im.getcolors(maxcolors=2000000) or [])
            im.convert("RGB").save(local_jpg, quality=85)
            print(f"  [Capture {name}] Size: {os.path.getsize(local_png)} bytes, Colors: {colors}")
        except Exception as e:
            print(f"  [Capture {name}] PIL error: {e}")

def measure_fps():
    sf_list = run_adb(["shell", "dumpsys", "SurfaceFlinger", "--list"]).stdout
    snk_layers = [l for l in sf_list.splitlines() if "org.snk" in l and "BLAST" in l]
    if not snk_layers:
        snk_layers = [l for l in sf_list.splitlines() if "SurfaceView" in l]
    print(f"[FPS] Target layers: {snk_layers}")
    for layer in snk_layers:
        quoted = shlex.quote(layer)
        lat = run_adb(["shell", f"dumpsys SurfaceFlinger --latency {quoted}"]).stdout
        lines = [l.strip() for l in lat.splitlines() if l.strip()]
        if len(lines) > 2:
            frame_times = []
            for fl in lines[1:]:
                parts = fl.split()
                if len(parts) == 3 and parts[1] != "0":
                    frame_times.append(int(parts[1]))
            if len(frame_times) >= 2:
                intervals = [(frame_times[k] - frame_times[k-1]) / 1e6 for k in range(1, len(frame_times))]
                valid = [dt for dt in intervals if dt > 0]
                if valid:
                    recent = valid[-30:]
                    avg_dt = sum(recent) / len(recent)
                    fps = 1000.0 / avg_dt if avg_dt > 0 else 0
                    print(f"  Layer {layer}: avg_dt={avg_dt:.2f}ms, estimated FPS={fps:.2f} Hz, samples={len(recent)}")

def main():
    print("[snk-test] Starting full intro-to-3D verification test on RG477M...")
    run_adb(["shell", "am", "force-stop", "org.snk.the1st.gamewindow"])
    run_adb(["logcat", "-c"])
    run_adb(["shell", "am", "start", "-n", "org.snk.the1st.gamewindow/org.snk.the1st.GameActivity"])
    
    print("[snk-test] Waiting 18s for title screen...")
    for sec in range(18, 0, -3):
        time.sleep(3)
        pid = get_pid()
        print(f"  Waiting... {sec}s left, PID={pid}")
        if not pid:
            print("[snk-test] ERROR: Game crashed before title screen!")
            sys.exit(1)

    capture_screen("snk_test_title")

    print("[snk-test] Step 1: Confirm New Game (Button A)...")
    send_btn(0, 300)
    time.sleep(2.5)

    print("[snk-test] Step 2: Confirm Difficulty (Button A)...")
    send_btn(0, 300)
    time.sleep(3.5)

    print("[snk-test] Step 3: Fast-advancing dialogue through 260 steps...")
    for i in range(1, 261):
        send_btn(0, 220)
        time.sleep(0.8)
        if i in (60, 120, 180, 235, 255):
            pid = get_pid()
            print(f"  Dialogue progress {i}/260, PID: {pid}")
            if not pid:
                print(f"[snk-test] CRASH at dialogue line {i}!")
                sys.exit(1)
            capture_screen(f"snk_test_step_{i}")

    print("[snk-test] Dialogue sequence 1-260 completed. Waiting 5s for 3D world scene...")
    time.sleep(5.0)

    pid = get_pid()
    print(f"[snk-test] Current PID after dialogue: {pid}")
    if not pid:
        print("[snk-test] ERROR: Game crashed entering 3D world!")
        sys.exit(1)

    capture_screen("snk_test_3d_prologue")
    print("[snk-test] Measuring SurfaceFlinger FPS in 3D scene:")
    measure_fps()

    # Step 4: Advance another 30 steps inside the 3D scene (Cassius / Estelle dialogue in 3D)
    print("[snk-test] Step 4: Advancing dialogue within 3D scene (261-290)...")
    for i in range(261, 291):
        send_btn(0, 220)
        time.sleep(0.8)
        if i % 10 == 0:
            print(f"  In-scene dialogue {i}/290, PID: {get_pid()}")

    time.sleep(3.0)
    capture_screen("snk_test_3d_in_scene")
    print("[snk-test] Measuring SurfaceFlinger FPS in active 3D scene:")
    measure_fps()

    # Check last 35 lines of guest_boot.log
    log_tail = run_adb(["shell", "tail -n 35 /sdcard/Android/data/org.snk.the1st.gamewindow/files/guest_boot.log"])
    print("[snk-test] guest_boot.log tail:\n" + log_tail.stdout)
    print("[snk-test] Verification run completed successfully!")

if __name__ == "__main__":
    main()
