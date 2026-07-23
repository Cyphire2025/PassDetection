package com.globalconnects.coordinator;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class AppUrlPolicyTest {
    @Test
    public void productionPolicyKeepsOnlyTheExactHttpsOriginInside() {
        AppUrlPolicy policy =
                AppUrlPolicy.forBuild(AppUrlPolicy.PRODUCTION_START_URL, false);

        assertTrue(policy.isTrusted("https://tech.gctravels.com/coordinator/groups/1"));
        assertTrue(policy.isTrusted("https://tech.gctravels.com/login?next=%2Fcoordinator"));
        assertTrue(policy.isTrusted("https://tech.gctravels.com:443/api/v1/auth/me"));
        assertFalse(policy.isTrusted("http://tech.gctravels.com/coordinator"));
        assertFalse(policy.isTrusted("https://evil.example/coordinator"));
        assertFalse(policy.isTrusted("https://tech.gctravels.com.evil.example/coordinator"));
        assertFalse(policy.isTrusted("https://user@tech.gctravels.com/coordinator"));
    }

    @Test(expected = IllegalArgumentException.class)
    public void productionBuildRejectsAlternativeHttpsOrigin() {
        AppUrlPolicy.forBuild("https://example.com/coordinator", false);
    }

    @Test(expected = IllegalArgumentException.class)
    public void productionBuildRejectsAlternativePath() {
        AppUrlPolicy.forBuild("https://tech.gctravels.com/login", false);
    }

    @Test
    public void localPolicyUsesTheLockedTrustworthyLoopbackOrigin() {
        AppUrlPolicy policy =
                AppUrlPolicy.forBuild(AppUrlPolicy.LOCAL_START_URL, true);

        assertTrue(policy.isTrusted("http://localhost:3100/login"));
        assertFalse(policy.isTrusted("http://localhost/coordinator"));
        assertFalse(policy.isTrusted("http://10.0.2.2:3100/coordinator"));
        assertFalse(policy.isTrusted("http://192.168.1.7:3000/coordinator"));
        assertFalse(policy.isTrusted("https://localhost:3100/coordinator"));
    }

    @Test(expected = IllegalArgumentException.class)
    public void localBuildRejectsEmulatorAliasOverride() {
        AppUrlPolicy.forBuild("http://10.0.2.2:3100/coordinator", true);
    }
}
