package com.globalconnects.coordinator;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.Set;

/**
 * Keeps every in-app top-level navigation on the one configured PWA origin.
 * External links are handed to Android instead of receiving the app's WebView
 * cookies or storage context.
 */
final class AppUrlPolicy {
    static final String PRODUCTION_START_URL =
            "https://tech.gctravels.com/coordinator";
    static final String LOCAL_START_URL =
            "http://localhost:3100/coordinator";
    private static final Set<String> LOCAL_DEBUG_HOSTS =
            Set.of("localhost");

    private final URI startUri;
    private final String scheme;
    private final String host;
    private final int effectivePort;

    static AppUrlPolicy forBuild(String configuredUrl, boolean localBuild) {
        String requiredUrl = localBuild ? LOCAL_START_URL : PRODUCTION_START_URL;
        if (!requiredUrl.equals(configuredUrl)) {
            throw new IllegalArgumentException(
                    localBuild
                            ? "Local build origin does not match the locked QA origin."
                            : "Production build origin does not match the locked production origin."
            );
        }
        return new AppUrlPolicy(configuredUrl, localBuild);
    }

    private AppUrlPolicy(String configuredUrl, boolean allowLocalCleartext) {
        try {
            URI parsed = new URI(configuredUrl).normalize();
            String parsedScheme = lower(parsed.getScheme());
            String parsedHost = lower(parsed.getHost());
            boolean localHttp = allowLocalCleartext
                    && "http".equals(parsedScheme)
                    && LOCAL_DEBUG_HOSTS.contains(parsedHost);

            if ((!"https".equals(parsedScheme) && !localHttp)
                    || parsedHost == null
                    || parsed.getRawUserInfo() != null
                    || parsed.getRawFragment() != null) {
                throw new IllegalArgumentException("The configured app URL is not a trusted origin.");
            }

            String path = parsed.getRawPath();
            if (path == null || path.isBlank() || "/".equals(path)) {
                parsed = new URI(
                        parsedScheme,
                        null,
                        parsedHost,
                        parsed.getPort(),
                        "/coordinator",
                        null,
                        null
                );
            }

            this.startUri = parsed;
            this.scheme = parsedScheme;
            this.host = parsedHost;
            this.effectivePort = effectivePort(parsedScheme, parsed.getPort());
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("The configured app URL is invalid.", exception);
        }
    }

    String startUrl() {
        return startUri.toString();
    }

    boolean isTrusted(String candidateUrl) {
        if (candidateUrl == null || candidateUrl.isBlank()) {
            return false;
        }

        try {
            URI candidate = new URI(candidateUrl);
            return !candidate.isOpaque()
                    && candidate.getRawUserInfo() == null
                    && scheme.equals(lower(candidate.getScheme()))
                    && host.equals(lower(candidate.getHost()))
                    && effectivePort == effectivePort(
                            lower(candidate.getScheme()),
                            candidate.getPort()
                    );
        } catch (URISyntaxException exception) {
            return false;
        }
    }

    private static int effectivePort(String scheme, int explicitPort) {
        if (explicitPort >= 0) {
            return explicitPort;
        }
        return "https".equals(scheme) ? 443 : 80;
    }

    private static String lower(String value) {
        return value == null ? null : value.toLowerCase(Locale.ROOT);
    }
}
