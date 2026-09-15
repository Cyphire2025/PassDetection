'use strict';

const { getSentryExpoConfig } = require('@sentry/react-native/metro');
const { withDirectFcmNotifications } = require('./scripts/direct-fcm-metro-resolver');

// Debug IDs are required for deterministic Hermes/source-map symbolication.
// Replay, feedback, and source-context injection stay disabled so the bundle
// cannot capture screen content or source snippets as telemetry attachments.
module.exports = withDirectFcmNotifications(getSentryExpoConfig(__dirname, {
  annotateReactComponents: false,
  includeWebReplay: false,
  includeWebFeedback: false,
  enableSourceContextInDevelopment: false,
}), __dirname);
