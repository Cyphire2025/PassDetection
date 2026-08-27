package com.globalconnects.coordinator;

import static org.junit.Assert.assertNotEquals;

import android.view.WindowManager;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

/** Native-window proof that PWA content is redacted before its first frame. */
@RunWith(AndroidJUnit4.class)
public final class MainActivityPrivacyTest {
    @Test
    public void sensitiveWindowPreventsScreenshotsAndRecentsSnapshots() {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> assertNotEquals(
                    0,
                    activity.getWindow().getAttributes().flags
                            & WindowManager.LayoutParams.FLAG_SECURE
            ));
        }
    }
}
