# WebView callbacks are framework overrides and do not need broad keep rules.
# Keep BuildConfig constants so the trusted origin remains available after R8.
-keep class com.globalconnects.coordinator.BuildConfig { *; }

# Preserve source information for actionable production crash reports.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
