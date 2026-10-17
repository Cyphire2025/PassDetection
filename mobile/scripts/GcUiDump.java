import android.app.UiAutomation;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.File;
import java.lang.reflect.Method;
import java.util.concurrent.TimeoutException;

/** adb QA snapshot for screens with a live countdown; never changes the app. */
public final class GcUiDump {
  public static void main(String[] args) throws Exception {
    Class<?> bridgeType = Class.forName("com.android.uiautomator.core.UiAutomationShellWrapper");
    Object bridge = bridgeType.getConstructor().newInstance();
    bridgeType.getMethod("connect").invoke(bridge);
    try {
      UiAutomation automation = (UiAutomation) bridgeType.getMethod("getUiAutomation").invoke(bridge);
      try { automation.waitForIdle(100, 600); } catch (TimeoutException ongoingCountdown) { /* Read current state. */ }
      AccessibilityNodeInfo root = automation.getRootInActiveWindow();
      for (int attempt = 0; root == null && attempt < 5; attempt++) {
        Thread.sleep(150);
        root = automation.getRootInActiveWindow();
      }
      if (root == null) { System.err.println("ERROR: No active accessibility window"); return; }
      Class<?> serializer = Class.forName("com.android.uiautomator.core.AccessibilityNodeInfoDumper");
      Method save = serializer.getMethod("dumpWindowToFile", AccessibilityNodeInfo.class, File.class, int.class, int.class, int.class);
      save.invoke(null, root, new File(args[0]), 0, Integer.parseInt(args[1]), Integer.parseInt(args[2]));
      System.out.println("Current UI snapshot saved");
    } finally {
      bridgeType.getMethod("disconnect").invoke(bridge);
    }
  }
}
