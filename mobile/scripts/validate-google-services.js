'use strict';

const { readFileSync } = require('node:fs');

const APP_ID = 'com.globalconnects.groupcompanion';

function validateGoogleServicesDocument(document) {
  const clients = Array.isArray(document?.client) ? document.client : [];
  const hasMatchingClient = clients.some(
    (client) =>
      client?.client_info?.android_client_info?.package_name === APP_ID,
  );
  if (!hasMatchingClient) {
    throw new Error(
      `GOOGLE_SERVICES_JSON has no Android client for ${APP_ID}.`,
    );
  }
}

function main() {
  const googleServicesFile = process.env.GOOGLE_SERVICES_JSON;
  if (!googleServicesFile) {
    throw new Error(
      'GOOGLE_SERVICES_JSON must point to the protected Firebase google-services.json file.',
    );
  }

  let document;
  try {
    document = JSON.parse(readFileSync(googleServicesFile, 'utf8'));
  } catch {
    throw new Error(
      'GOOGLE_SERVICES_JSON must point to a readable, valid JSON file.',
    );
  }
  validateGoogleServicesDocument(document);
  console.log('Android Firebase client configuration passed.');
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}

module.exports = { validateGoogleServicesDocument };
