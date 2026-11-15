import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def method(source, signature):
    begin = source.index(signature)
    end = begin + len(signature)
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end]


class PadLifecycleTests(unittest.TestCase):
    def test_pause_releases_keys_and_sticks_without_disconnect(self):
        source = (ROOT / 'src/android/app/java/org/snk/the1st/GameActivity.java').read_text()
        publish = method(source, 'private void publishPad() {')
        pause = method(source, '@Override protected void onPause() {')
        clear = method(source, 'private void clearInput() {')
        program = r'''
class Parent { protected void onPause() {} }
class Log { static void i(String tag, String text) {} }
class GameWindowNative {
    static boolean connected;
    static long buttons;
    static int lx, ly, rx, ry, focus;
    static void setFocusState(int state) { focus = state; }
    static void setPadState(boolean attached, long keys, int x, int y, int z, int w) {
        connected = attached; buttons = keys; lx = x; ly = y; rx = z; ry = w;
    }
}
public class PadLifecycle extends Parent {
    static final String TAG = "test";
    boolean resumed = true, padConnected = true;
    long padButtons, axisButtons, touchButtons;
    int padLx, padLy, padRx, padRy, touchLx, touchLy, touchRx, touchRy;
    TouchPad touchPad = new TouchPad(this);
    static class TouchPad {
        PadLifecycle owner;
        int lsId, rsId, dragMode;
        long pressed;
        TouchPad(PadLifecycle activity) { owner = activity; }
''' + clear + r'''
    }
''' + publish + '\n' + pause + r'''
    public static void main(String[] args) {
        PadLifecycle activity = new PadLifecycle();
        activity.padButtons = 1; activity.axisButtons = 2; activity.touchButtons = 4;
        activity.padLx = 100; activity.padRy = 200; activity.touchLx = 300;
        activity.touchPad.lsId = 7; activity.touchPad.pressed = 4;
        activity.publishPad();
        if (!GameWindowNative.connected || GameWindowNative.buttons != 7
                || GameWindowNative.lx != 300 || GameWindowNative.ry != 200)
            throw new AssertionError("foreground input");
        activity.onPause();
        if (!GameWindowNative.connected || GameWindowNative.buttons != 0
                || GameWindowNative.lx != 0 || GameWindowNative.ly != 0
                || GameWindowNative.rx != 0 || GameWindowNative.ry != 0
                || GameWindowNative.focus != 3 || activity.resumed
                || activity.touchPad.lsId != -1 || activity.touchPad.pressed != 0)
            throw new AssertionError("pause must release input and keep controller attached");
        activity.resumed = true;
        activity.publishPad();
        if (!GameWindowNative.connected || GameWindowNative.buttons != 0)
            throw new AssertionError("resume input");
        activity.touchPad = null;
        activity.onPause();
        if (!GameWindowNative.connected || GameWindowNative.buttons != 0)
            throw new AssertionError("pause without a touch view");
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'PadLifecycle.java'
            code.write_text(program)
            subprocess.run(['javac', '-d', str(path), str(code)], check=True, capture_output=True)
            result = subprocess.run(['java', '-cp', str(path), 'PadLifecycle'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
