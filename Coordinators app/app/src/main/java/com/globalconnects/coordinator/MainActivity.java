package com.globalconnects.coordinator;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.ClientCertRequest;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.HttpAuthHandler;
import android.webkit.MimeTypeMap;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.ServiceWorkerController;
import android.webkit.ServiceWorkerWebSettings;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import androidx.core.content.FileProvider;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Minimal native host for the coordinator PWA.
 *
 * <p>The WebView has no JavaScript bridge. It only keeps the configured origin
 * in-process, while Android handles external links, camera permission, file
 * selection, downloads, lifecycle, renderer recovery, and back navigation.</p>
 */
public final class MainActivity extends ComponentActivity {
    private static final String WEB_STATE_KEY = "coordinator-web-state";
    private static final int MAX_SELECTED_FILES = 20;
    private static final long MAX_FILE_BYTES = 25L * 1024L * 1024L;
    private static final long MAX_TOTAL_SELECTION_BYTES = 100L * 1024L * 1024L;
    private static final long CAPTURE_MAX_AGE_MILLIS = 60L * 60L * 1000L;
    private static final long CAPTURE_DELETE_DELAY_MILLIS = 15L * 60L * 1000L;
    private static final Pattern MIME_TYPE_PATTERN = Pattern.compile(
            "^[a-z0-9][a-z0-9!#$&^_.+-]*/(?:\\*|[a-z0-9][a-z0-9!#$&^_.+-]*)$"
    );
    private static final Set<String> EXTERNAL_SCHEMES =
            Set.of("https", "mailto", "tel", "sms", "geo");

    private AppUrlPolicy appUrlPolicy;
    private FrameLayout webContainer;
    private WebView webView;
    private ProgressBar loadingIndicator;
    private View errorOverlay;
    private TextView errorTitle;
    private TextView errorMessage;
    private Button retryButton;
    private Runnable retryAction;
    private boolean mainFrameFailed;
    private boolean destroyed;

    private PermissionRequest pendingWebCameraRequest;
    private ValueCallback<Uri[]> pendingFileCallback;
    private WebChromeClient.FileChooserParams pendingFileParams;
    private String[] pendingAcceptedMimeTypes = new String[]{"*/*"};
    private Uri pendingCaptureUri;
    private File pendingCaptureFile;
    private ActivityResultLauncher<Intent> fileChooserLauncher;
    private ActivityResultLauncher<String> webCameraPermissionLauncher;
    private ActivityResultLauncher<String> fileCameraPermissionLauncher;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        setTheme(R.style.Theme_Coordinator);
        super.onCreate(savedInstanceState);
        enforceSensitiveWindowPrivacy();
        configureSystemBars();
        setContentView(R.layout.activity_main);
        configureWindowInsets();
        webCameraPermissionLauncher = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(),
                this::handleWebCameraPermissionResult
        );
        fileCameraPermissionLauncher = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(),
                this::handleFileCameraPermissionResult
        );
        fileChooserLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> handleFileChooserResult(
                        result.getResultCode(),
                        result.getData()
                )
        );
        pruneStaleCaptureFiles();

        appUrlPolicy = AppUrlPolicy.forBuild(
                BuildConfig.APP_URL,
                BuildConfig.ALLOW_LOCAL_CLEARTEXT
        );
        webContainer = findViewById(R.id.web_container);
        webView = findViewById(R.id.coordinator_web_view);
        loadingIndicator = findViewById(R.id.loading_indicator);
        errorOverlay = findViewById(R.id.error_overlay);
        errorTitle = findViewById(R.id.error_title);
        errorMessage = findViewById(R.id.error_message);
        retryButton = findViewById(R.id.retry_button);
        retryButton.setOnClickListener(view -> {
            Runnable action = retryAction;
            if (action != null) {
                action.run();
            }
        });

        configureServiceWorkerSecurity();
        configureWebView(webView);
        registerBackHandler();

        Bundle webState = savedInstanceState == null
                ? null
                : savedInstanceState.getBundle(WEB_STATE_KEY);
        if (webState == null || webView.restoreState(webState) == null) {
            loadStartUrl();
        } else {
            loadingIndicator.setVisibility(View.VISIBLE);
        }
    }

    /**
     * Attendance and passenger screens are sensitive by default. Keeping this
     * policy at the native window boundary also redacts Android's recents/task
     * snapshot and prevents ordinary screenshots or screen recording even if
     * web content is restored before its route-level UI has rendered.
     */
    private void enforceSensitiveWindowPrivacy() {
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
    }

    private void configureSystemBars() {
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        WindowInsetsControllerCompat controller = WindowCompat.getInsetsController(
                getWindow(),
                getWindow().getDecorView()
        );
        controller.setAppearanceLightStatusBars(true);
        controller.setAppearanceLightNavigationBars(true);
    }

    private void configureWindowInsets() {
        View root = findViewById(R.id.root);
        ViewCompat.setOnApplyWindowInsetsListener(root, (view, windowInsets) -> {
            Insets safeInsets = windowInsets.getInsets(
                    WindowInsetsCompat.Type.systemBars()
                            | WindowInsetsCompat.Type.displayCutout()
            );
            view.setPadding(
                    safeInsets.left,
                    safeInsets.top,
                    safeInsets.right,
                    safeInsets.bottom
            );
            return windowInsets;
        });
        ViewCompat.requestApplyInsets(root);
    }

    private void configureServiceWorkerSecurity() {
        try {
            ServiceWorkerWebSettings serviceWorkerSettings = ServiceWorkerController
                    .getInstance()
                    .getServiceWorkerWebSettings();
            serviceWorkerSettings.setAllowContentAccess(false);
            serviceWorkerSettings.setAllowFileAccess(false);
            serviceWorkerSettings.setBlockNetworkLoads(false);
            serviceWorkerSettings.setCacheMode(WebSettings.LOAD_DEFAULT);
        } catch (RuntimeException ignored) {
            // A device without a usable system WebView will surface its own
            // main-frame error when the page starts.
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView(WebView view) {
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSafeBrowsingEnabled(true);
        settings.setGeolocationEnabled(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setLoadWithOverviewMode(false);
        settings.setUseWideViewPort(true);
        float fontScale = getResources().getConfiguration().fontScale;
        settings.setTextZoom(Math.max(85, Math.min(Math.round(100f * fontScale), 200)));
        settings.setDefaultTextEncodingName("UTF-8");
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUserAgentString(
                settings.getUserAgentString()
                        + " GlobalConnectsCoordinator/"
                        + BuildConfig.VERSION_NAME
        );

        view.setBackgroundColor(getColor(R.color.surface));
        view.setOverScrollMode(View.OVER_SCROLL_NEVER);
        view.setVerticalScrollBarEnabled(false);
        view.setHorizontalScrollBarEnabled(false);
        view.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_BOUND, true);
        view.setWebViewClient(new TrustedWebViewClient());
        view.setWebChromeClient(new CoordinatorChromeClient());
        view.setDownloadListener(this::startTrustedDownload);

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(view, false);

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
    }

    private void loadStartUrl() {
        if (webView == null) {
            replaceWebView();
        }
        mainFrameFailed = false;
        hideError();
        loadingIndicator.setVisibility(View.VISIBLE);
        webView.loadUrl(appUrlPolicy.startUrl());
    }

    private void replaceWebView() {
        WebView replacement = new WebView(this);
        replacement.setId(R.id.coordinator_web_view);
        replacement.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
        webContainer.addView(replacement, 0);
        webView = replacement;
        configureWebView(replacement);
    }

    private void recoverFromRendererLoss(WebView failedView) {
        if (failedView != webView) {
            return;
        }
        cancelPendingFileChooser();
        denyPendingWebCameraRequest();
        webContainer.removeView(failedView);
        failedView.destroy();
        webView = null;
        mainFrameFailed = true;
        showError(
                R.string.renderer_error_title,
                R.string.renderer_error_message,
                this::loadStartUrl
        );
    }

    private void showError(int titleResource, int messageResource, Runnable action) {
        if (destroyed) {
            return;
        }
        loadingIndicator.setVisibility(View.GONE);
        errorTitle.setText(titleResource);
        errorMessage.setText(messageResource);
        retryAction = action;
        retryButton.setVisibility(action == null ? View.GONE : View.VISIBLE);
        errorOverlay.setVisibility(View.VISIBLE);
        ViewCompat.setAccessibilityPaneTitle(errorOverlay, errorTitle.getText());
        if (webView != null) {
            webView.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        }
        errorOverlay.post(() -> {
            errorTitle.requestFocus();
        });
    }

    private void hideError() {
        retryAction = null;
        errorOverlay.setVisibility(View.GONE);
        ViewCompat.setAccessibilityPaneTitle(errorOverlay, null);
        if (webView != null) {
            webView.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
        }
    }

    private void registerBackHandler() {
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                handleBack();
            }
        });
    }

    private void handleBack() {
        if (errorOverlay.getVisibility() == View.VISIBLE
                && webView != null
                && webView.canGoBack()) {
            hideError();
            webView.goBack();
            return;
        }
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        finishAfterTransition();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
            webView.resumeTimers();
        }
    }

    @Override
    protected void onPause() {
        CookieManager.getInstance().flush();
        if (webView != null) {
            webView.onPause();
            webView.pauseTimers();
        }
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(@NonNull Bundle outState) {
        if (webView != null) {
            Bundle webState = new Bundle();
            webView.saveState(webState);
            outState.putBundle(WEB_STATE_KEY, webState);
        }
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        cancelPendingFileChooser();
        denyPendingWebCameraRequest();
        if (webView != null) {
            webContainer.removeView(webView);
            webView.stopLoading();
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private boolean routeExternal(Uri uri) {
        String scheme = uri.getScheme();
        if (scheme == null || !EXTERNAL_SCHEMES.contains(scheme.toLowerCase(Locale.ROOT))) {
            Toast.makeText(this, R.string.blocked_link, Toast.LENGTH_LONG).show();
            return false;
        }

        Intent intent = new Intent(Intent.ACTION_VIEW, uri);
        intent.addCategory(Intent.CATEGORY_BROWSABLE);
        intent.setComponent(null);
        intent.setSelector(null);
        if (intent.resolveActivity(getPackageManager()) == null) {
            Toast.makeText(this, R.string.no_compatible_app, Toast.LENGTH_LONG).show();
            return false;
        }
        startActivity(intent);
        return true;
    }

    private void handleWebCameraPermission(PermissionRequest request) {
        boolean trustedOrigin = request.getOrigin() != null
                && appUrlPolicy.isTrusted(request.getOrigin().toString());
        boolean asksForVideo = Arrays.asList(request.getResources())
                .contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE);

        if (!trustedOrigin || !asksForVideo || destroyed || pendingWebCameraRequest != null) {
            request.deny();
            return;
        }

        if (checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED) {
            request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            return;
        }

        pendingWebCameraRequest = request;
        webCameraPermissionLauncher.launch(Manifest.permission.CAMERA);
    }

    private void handleWebCameraPermissionCanceled(PermissionRequest request) {
        if (pendingWebCameraRequest == request) {
            pendingWebCameraRequest = null;
        }
    }

    private void denyPendingWebCameraRequest() {
        PermissionRequest request = pendingWebCameraRequest;
        pendingWebCameraRequest = null;
        if (request != null) {
            request.deny();
        }
    }

    private boolean beginFileChooser(
            ValueCallback<Uri[]> callback,
            WebChromeClient.FileChooserParams params
    ) {
        cancelPendingFileChooser();
        int mode = params.getMode();
        if (mode != WebChromeClient.FileChooserParams.MODE_OPEN
                && mode != WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) {
            callback.onReceiveValue(null);
            Toast.makeText(this, R.string.unsupported_file_selection, Toast.LENGTH_LONG).show();
            return true;
        }

        pendingFileCallback = callback;
        pendingFileParams = params;
        pendingAcceptedMimeTypes = sanitizeMimeTypes(params.getAcceptTypes());

        boolean cameraCaptureRequested = params.isCaptureEnabled()
                && mode == WebChromeClient.FileChooserParams.MODE_OPEN
                && acceptsImage(pendingAcceptedMimeTypes)
                && getPackageManager().hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY);

        if (cameraCaptureRequested
                && checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            fileCameraPermissionLauncher.launch(Manifest.permission.CAMERA);
            return true;
        }

        launchFileChooser(cameraCaptureRequested);
        return true;
    }

    private void launchFileChooser(boolean allowCameraCapture) {
        if (pendingFileCallback == null || pendingFileParams == null) {
            return;
        }

        Intent documentIntent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        documentIntent.addCategory(Intent.CATEGORY_OPENABLE);
        documentIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        documentIntent.setType(preferredChooserMimeType(pendingAcceptedMimeTypes));
        if (pendingAcceptedMimeTypes.length > 1) {
            documentIntent.putExtra(Intent.EXTRA_MIME_TYPES, pendingAcceptedMimeTypes);
        }
        documentIntent.putExtra(
                Intent.EXTRA_ALLOW_MULTIPLE,
                pendingFileParams.getMode()
                        == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE
        );

        Intent launchIntent = documentIntent;
        Intent cameraIntent = allowCameraCapture ? createCameraCaptureIntent() : null;
        if (cameraIntent != null && pendingFileParams.isCaptureEnabled()) {
            launchIntent = cameraIntent;
        } else if (cameraIntent != null) {
            Intent chooser = Intent.createChooser(
                    documentIntent,
                    getString(R.string.choose_file)
            );
            chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{cameraIntent});
            launchIntent = chooser;
        } else {
            launchIntent = Intent.createChooser(
                    documentIntent,
                    getString(R.string.choose_file)
            );
        }

        try {
            fileChooserLauncher.launch(launchIntent);
        } catch (RuntimeException exception) {
            cancelPendingFileChooser();
            Toast.makeText(this, R.string.no_compatible_app, Toast.LENGTH_LONG).show();
        }
    }

    private Intent createCameraCaptureIntent() {
        Intent cameraIntent = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
        if (cameraIntent.resolveActivity(getPackageManager()) == null) {
            return null;
        }

        File baseDirectory = getExternalCacheDir();
        if (baseDirectory == null) {
            baseDirectory = getCacheDir();
        }
        File captureDirectory = new File(baseDirectory, "coordinator-captures");
        if (!captureDirectory.exists() && !captureDirectory.mkdirs()) {
            return null;
        }

        try {
            pendingCaptureFile = File.createTempFile(
                    "coordinator-capture-",
                    ".jpg",
                    captureDirectory
            );
            pendingCaptureUri = FileProvider.getUriForFile(
                    this,
                    BuildConfig.APPLICATION_ID + ".files",
                    pendingCaptureFile
            );
        } catch (IOException | IllegalArgumentException exception) {
            pendingCaptureFile = null;
            pendingCaptureUri = null;
            return null;
        }

        cameraIntent.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, pendingCaptureUri);
        cameraIntent.setClipData(ClipData.newRawUri(
                getString(R.string.camera_capture),
                pendingCaptureUri
        ));
        int grantFlags = Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION;
        cameraIntent.addFlags(grantFlags);

        List<ResolveInfo> handlers = getPackageManager().queryIntentActivities(
                cameraIntent,
                PackageManager.MATCH_DEFAULT_ONLY
        );
        for (ResolveInfo handler : handlers) {
            grantUriPermission(
                    handler.activityInfo.packageName,
                    pendingCaptureUri,
                    grantFlags
            );
        }
        return cameraIntent;
    }

    private void handleFileChooserResult(int resultCode, Intent data) {
        ValueCallback<Uri[]> callback = pendingFileCallback;
        Uri[] validatedUris = resultCode == RESULT_OK
                ? collectValidatedFileUris(data)
                : null;
        if (callback != null) {
            callback.onReceiveValue(validatedUris);
        }

        boolean usedCapture = validatedUris != null
                && pendingCaptureUri != null
                && Arrays.asList(validatedUris).contains(pendingCaptureUri);
        File completedCaptureFile = pendingCaptureFile;
        revokeCapturePermissions();
        if (usedCapture && completedCaptureFile != null) {
            scheduleCaptureDeletion(completedCaptureFile);
        } else if (completedCaptureFile != null) {
            // A cancelled camera capture contains no user data worth retaining.
            //noinspection ResultOfMethodCallIgnored
            completedCaptureFile.delete();
        }
        clearFileChooserState();

        if (resultCode == RESULT_OK && validatedUris == null) {
            Toast.makeText(this, R.string.invalid_file_selection, Toast.LENGTH_LONG).show();
        }
    }

    private void scheduleCaptureDeletion(File captureFile) {
        new Handler(Looper.getMainLooper()).postDelayed(
                () -> {
                    if (isOwnedCaptureFile(captureFile)) {
                        //noinspection ResultOfMethodCallIgnored
                        captureFile.delete();
                    }
                },
                CAPTURE_DELETE_DELAY_MILLIS
        );
    }

    private void pruneStaleCaptureFiles() {
        pruneCaptureDirectory(new File(getCacheDir(), "coordinator-captures"));
        File externalCache = getExternalCacheDir();
        if (externalCache != null) {
            pruneCaptureDirectory(new File(externalCache, "coordinator-captures"));
        }
    }

    private void pruneCaptureDirectory(File captureDirectory) {
        File[] captures = captureDirectory.listFiles(
                file -> file.isFile() && file.getName().startsWith("coordinator-capture-")
        );
        if (captures == null) {
            return;
        }
        long cutoff = System.currentTimeMillis() - CAPTURE_MAX_AGE_MILLIS;
        for (File capture : captures) {
            if (capture.lastModified() < cutoff && isOwnedCaptureFile(capture)) {
                //noinspection ResultOfMethodCallIgnored
                capture.delete();
            }
        }
    }

    private boolean isOwnedCaptureFile(File candidate) {
        if (candidate == null || !candidate.getName().startsWith("coordinator-capture-")) {
            return false;
        }
        try {
            File parent = candidate.getCanonicalFile().getParentFile();
            File internalCaptureDirectory = new File(
                    getCacheDir(),
                    "coordinator-captures"
            ).getCanonicalFile();
            if (internalCaptureDirectory.equals(parent)) {
                return true;
            }
            File externalCache = getExternalCacheDir();
            return externalCache != null
                    && new File(externalCache, "coordinator-captures")
                    .getCanonicalFile()
                    .equals(parent);
        } catch (IOException exception) {
            return false;
        }
    }

    private Uri[] collectValidatedFileUris(Intent data) {
        List<Uri> candidates = new ArrayList<>();
        if (data != null && data.getClipData() != null) {
            ClipData clipData = data.getClipData();
            int count = Math.min(clipData.getItemCount(), MAX_SELECTED_FILES);
            for (int index = 0; index < count; index++) {
                candidates.add(clipData.getItemAt(index).getUri());
            }
        } else if (data != null && data.getData() != null) {
            candidates.add(data.getData());
        } else if (pendingCaptureUri != null) {
            candidates.add(pendingCaptureUri);
        }

        LinkedHashSet<Uri> accepted = new LinkedHashSet<>();
        long totalBytes = 0L;
        for (Uri uri : candidates) {
            long contentBytes = acceptedContentSize(uri, pendingAcceptedMimeTypes);
            if (contentBytes > 0L
                    && contentBytes <= MAX_FILE_BYTES
                    && totalBytes + contentBytes <= MAX_TOTAL_SELECTION_BYTES) {
                accepted.add(uri);
                totalBytes += contentBytes;
            }
        }
        return accepted.isEmpty() ? null : accepted.toArray(new Uri[0]);
    }

    private long acceptedContentSize(Uri uri, String[] acceptedMimeTypes) {
        if (uri == null || !"content".equalsIgnoreCase(uri.getScheme())) {
            return -1L;
        }

        String actualMimeType;
        if (uri.equals(pendingCaptureUri)) {
            actualMimeType = "image/jpeg";
        } else {
            try {
                actualMimeType = getContentResolver().getType(uri);
            } catch (RuntimeException exception) {
                return -1L;
            }
        }
        if (actualMimeType == null) {
            if (!Arrays.asList(acceptedMimeTypes).contains("*/*")) {
                return -1L;
            }
        } else {
            String normalizedActual = actualMimeType.toLowerCase(Locale.ROOT);
            boolean mimeAccepted = false;
            for (String accepted : acceptedMimeTypes) {
                if ("*/*".equals(accepted)
                        || accepted.equals(normalizedActual)
                        || (accepted.endsWith("/*")
                        && normalizedActual.startsWith(
                                accepted.substring(0, accepted.length() - 1)
                        ))) {
                    mimeAccepted = true;
                    break;
                }
            }
            if (!mimeAccepted) {
                return -1L;
            }
        }

        if (uri.equals(pendingCaptureUri) && pendingCaptureFile != null) {
            return pendingCaptureFile.length();
        }

        try (Cursor cursor = getContentResolver().query(
                uri,
                new String[]{OpenableColumns.SIZE},
                null,
                null,
                null
        )) {
            if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) {
                long declaredSize = cursor.getLong(0);
                if (declaredSize >= 0L) {
                    return declaredSize;
                }
            }
        } catch (RuntimeException ignored) {
            // Fall through to the file-descriptor size, if the provider offers one.
        }

        try (ParcelFileDescriptor descriptor =
                     getContentResolver().openFileDescriptor(uri, "r")) {
            return descriptor == null ? -1L : descriptor.getStatSize();
        } catch (IOException | RuntimeException exception) {
            return -1L;
        }
    }

    private static String[] sanitizeMimeTypes(String[] rawAcceptTypes) {
        LinkedHashSet<String> accepted = new LinkedHashSet<>();
        if (rawAcceptTypes != null) {
            for (String rawGroup : rawAcceptTypes) {
                if (rawGroup == null) {
                    continue;
                }
                for (String rawType : rawGroup.split(",")) {
                    String candidate = rawType.trim().toLowerCase(Locale.ROOT);
                    if (candidate.startsWith(".")) {
                        String extension = candidate.substring(1);
                        candidate = MimeTypeMap.getSingleton()
                                .getMimeTypeFromExtension(extension);
                        if (candidate == null) {
                            continue;
                        }
                    }
                    int parametersStart = candidate.indexOf(';');
                    if (parametersStart >= 0) {
                        candidate = candidate.substring(0, parametersStart).trim();
                    }
                    if ("*/*".equals(candidate) || MIME_TYPE_PATTERN.matcher(candidate).matches()) {
                        accepted.add(candidate);
                    }
                }
            }
        }
        if (accepted.isEmpty()) {
            accepted.add("*/*");
        }
        return accepted.toArray(new String[0]);
    }

    private static boolean acceptsImage(String[] acceptedMimeTypes) {
        for (String mimeType : acceptedMimeTypes) {
            if ("*/*".equals(mimeType)
                    || "image/*".equals(mimeType)
                    || mimeType.startsWith("image/")) {
                return true;
            }
        }
        return false;
    }

    private static String preferredChooserMimeType(String[] acceptedMimeTypes) {
        return acceptedMimeTypes.length == 1 ? acceptedMimeTypes[0] : "*/*";
    }

    private void cancelPendingFileChooser() {
        if (pendingFileCallback != null) {
            pendingFileCallback.onReceiveValue(null);
        }
        revokeCapturePermissions();
        if (pendingCaptureFile != null) {
            //noinspection ResultOfMethodCallIgnored
            pendingCaptureFile.delete();
        }
        clearFileChooserState();
    }

    private void revokeCapturePermissions() {
        if (pendingCaptureUri != null) {
            revokeUriPermission(
                    pendingCaptureUri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION
                            | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            );
        }
    }

    private void clearFileChooserState() {
        pendingFileCallback = null;
        pendingFileParams = null;
        pendingAcceptedMimeTypes = new String[]{"*/*"};
        pendingCaptureUri = null;
        pendingCaptureFile = null;
    }

    private void handleWebCameraPermissionResult(boolean granted) {
        PermissionRequest request = pendingWebCameraRequest;
        pendingWebCameraRequest = null;
        if (request != null) {
            if (granted) {
                request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            } else {
                request.deny();
                showCameraSettingsIfPermanentlyDenied();
            }
        }
    }

    private void handleFileCameraPermissionResult(boolean granted) {
        if (!granted) {
            Toast.makeText(
                    this,
                    R.string.camera_permission_denied,
                    Toast.LENGTH_LONG
            ).show();
        }
        launchFileChooser(granted);
    }

    private void showCameraSettingsIfPermanentlyDenied() {
        if (shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) {
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle(R.string.camera_permission_title)
                .setMessage(R.string.camera_permission_message)
                .setNegativeButton(R.string.close, null)
                .setPositiveButton(R.string.open_settings, (dialog, which) -> {
                    Intent settingsIntent = new Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.fromParts("package", getPackageName(), null)
                    );
                    startActivity(settingsIntent);
                })
                .show();
    }

    private void startTrustedDownload(
            String url,
            String userAgent,
            String contentDisposition,
            String mimeType,
            long contentLength
    ) {
        if (!appUrlPolicy.isTrusted(url)) {
            routeExternal(Uri.parse(url));
            return;
        }

        try {
            Uri uri = Uri.parse(url);
            DownloadManager.Request request = new DownloadManager.Request(uri);
            request.setAllowedOverMetered(true);
            request.setAllowedOverRoaming(false);
            request.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
            );

            String safeMimeType = normalizeSingleMimeType(mimeType);
            if (safeMimeType != null) {
                request.setMimeType(safeMimeType);
            }
            if (userAgent != null && !containsNewline(userAgent)) {
                request.addRequestHeader("User-Agent", userAgent);
            }
            String cookies = CookieManager.getInstance().getCookie(url);
            if (cookies != null && !cookies.isBlank() && !containsNewline(cookies)) {
                request.addRequestHeader("Cookie", cookies);
            }

            String guessedName = URLUtil.guessFileName(url, contentDisposition, safeMimeType);
            String safeName = sanitizeFileName(guessedName);
            request.setTitle(safeName);
            request.setDestinationInExternalFilesDir(
                    this,
                    Environment.DIRECTORY_DOWNLOADS,
                    safeName
            );

            DownloadManager manager =
                    (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            manager.enqueue(request);
            Toast.makeText(
                    this,
                    getString(R.string.download_started)
                            + ". "
                            + getString(R.string.file_saved_private),
                    Toast.LENGTH_LONG
            ).show();
        } catch (RuntimeException exception) {
            Toast.makeText(this, R.string.download_failed, Toast.LENGTH_LONG).show();
        }
    }

    private static String normalizeSingleMimeType(String mimeType) {
        if (mimeType == null) {
            return null;
        }
        String candidate = mimeType.trim().toLowerCase(Locale.ROOT);
        int parametersStart = candidate.indexOf(';');
        if (parametersStart >= 0) {
            candidate = candidate.substring(0, parametersStart).trim();
        }
        return MIME_TYPE_PATTERN.matcher(candidate).matches() ? candidate : null;
    }

    private static boolean containsNewline(String value) {
        return value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0;
    }

    private static String sanitizeFileName(String fileName) {
        String sanitized = fileName == null
                ? "coordinator-download"
                : fileName.replaceAll("[^A-Za-z0-9._ -]", "_");
        sanitized = sanitized.replaceAll("^\\.+", "").trim();
        if (sanitized.isBlank()) {
            return "coordinator-download";
        }
        return sanitized.length() > 100 ? sanitized.substring(0, 100) : sanitized;
    }

    private final class TrustedWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            if ("about:blank".equals(url) || appUrlPolicy.isTrusted(url)) {
                return false;
            }
            if (!request.isForMainFrame()) {
                return true;
            }
            routeExternal(request.getUrl());
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            super.onPageStarted(view, url, favicon);
            if (appUrlPolicy.isTrusted(url)) {
                mainFrameFailed = false;
                loadingIndicator.setVisibility(View.VISIBLE);
            }
        }

        @Override
        public void onPageCommitVisible(WebView view, String url) {
            super.onPageCommitVisible(view, url);
            if (appUrlPolicy.isTrusted(url)) {
                mainFrameFailed = false;
                loadingIndicator.setVisibility(View.GONE);
                hideError();
            }
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            if (!mainFrameFailed && appUrlPolicy.isTrusted(url)) {
                loadingIndicator.setVisibility(View.GONE);
                hideError();
            }
        }

        @Override
        public void onReceivedError(
                WebView view,
                WebResourceRequest request,
                WebResourceError error
        ) {
            super.onReceivedError(view, request, error);
            if (!request.isForMainFrame()) {
                return;
            }
            mainFrameFailed = true;
            showError(
                    R.string.network_error_title,
                    R.string.network_error_message,
                    MainActivity.this::loadStartUrl
            );
        }

        @Override
        public void onReceivedHttpError(
                WebView view,
                WebResourceRequest request,
                WebResourceResponse errorResponse
        ) {
            super.onReceivedHttpError(view, request, errorResponse);
            if (request.isForMainFrame() && errorResponse.getStatusCode() >= 500) {
                mainFrameFailed = true;
                showError(
                        R.string.server_error_title,
                        R.string.server_error_message,
                        MainActivity.this::loadStartUrl
                );
            }
        }

        @Override
        public void onReceivedSslError(
                WebView view,
                SslErrorHandler handler,
                android.net.http.SslError error
        ) {
            handler.cancel();
            mainFrameFailed = true;
            showError(
                    R.string.secure_connection_error_title,
                    R.string.secure_connection_error_message,
                    MainActivity.this::loadStartUrl
            );
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            recoverFromRendererLoss(view);
            return true;
        }

        @Override
        public void onFormResubmission(WebView view, Message dontResend, Message resend) {
            dontResend.sendToTarget();
        }

        @Override
        public void onReceivedHttpAuthRequest(
                WebView view,
                HttpAuthHandler handler,
                String host,
                String realm
        ) {
            handler.cancel();
        }

        @Override
        public void onReceivedClientCertRequest(WebView view, ClientCertRequest request) {
            request.cancel();
        }
    }

    private final class CoordinatorChromeClient extends WebChromeClient {
        @Override
        public void onProgressChanged(WebView view, int newProgress) {
            super.onProgressChanged(view, newProgress);
            if (newProgress >= 100 && !mainFrameFailed) {
                loadingIndicator.setVisibility(View.GONE);
            }
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            runOnUiThread(() -> handleWebCameraPermission(request));
        }

        @Override
        public void onPermissionRequestCanceled(PermissionRequest request) {
            runOnUiThread(() -> handleWebCameraPermissionCanceled(request));
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(
                String origin,
                GeolocationPermissions.Callback callback
        ) {
            callback.invoke(origin, false, false);
        }

        @Override
        public boolean onShowFileChooser(
                WebView view,
                ValueCallback<Uri[]> filePathCallback,
                FileChooserParams fileChooserParams
        ) {
            return beginFileChooser(filePathCallback, fileChooserParams);
        }
    }
}
