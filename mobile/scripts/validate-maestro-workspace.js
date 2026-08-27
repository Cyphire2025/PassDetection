/* global __dirname */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { parseAllDocuments, parseDocument } = require('yaml');

const projectRoot = path.resolve(__dirname, '..');
const maestroRoot = path.join(projectRoot, '.maestro');
const expectedAppId = 'com.globalconnects.groupcompanion';
const expectedMaestroVersion = '2.7.0';

function read(relativePath) {
  return fs.readFileSync(path.join(projectRoot, relativePath), 'utf8');
}

function listYaml(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const resolved = path.join(directory, entry.name);
    if (entry.isDirectory()) return listYaml(resolved);
    return /\.ya?ml$/i.test(entry.name) ? [resolved] : [];
  });
}

const errors = [];
const releaseHermesCoreFlows = [
  '.maestro/release-hermes-auth-smoke.yml',
  '.maestro/flows/verified-activation-link.yml',
  '.maestro/flows/passenger-document-cache.yml',
  '.maestro/flows/account-switch-isolation.yml',
  '.maestro/flows/manager-operational-journey.yml',
  '.maestro/flows/passenger-trip-journey.yml',
  '.maestro/flows/passenger-interrupted-auth.yml',
];
for (const filePath of listYaml(maestroRoot)) {
  const source = fs.readFileSync(filePath, 'utf8');
  const relative = path.relative(projectRoot, filePath).replace(/\\/g, '/');
  const documents = parseAllDocuments(source);
  for (const document of documents) {
    if (document.errors.length) {
      errors.push(`${relative} is not valid YAML: ${document.errors[0].message}`);
    }
  }
  if (path.basename(filePath) !== 'config.yaml') {
    const configuration = documents[0]?.toJS();
    if (configuration?.appId !== expectedAppId) {
      errors.push(`${relative} must use the canonical mobile app id.`);
    }
  }
  for (const line of source.split(/\r?\n/)) {
    const inputMatch = line.match(/^\s*-?\s*inputText:\s*(.+?)\s*$/);
    if (inputMatch && !/^\$\{MAESTRO_[A-Z0-9_]+\}$/.test(inputMatch[1])) {
      errors.push(`${relative} contains a literal inputText value; use a protected MAESTRO_ variable.`);
    }
  }
  if (/\b(?:password|otp|phone|email)\s*:\s*["']?[^$\s#]/i.test(source)) {
    errors.push(`${relative} appears to embed fixture credentials.`);
  }
  if (/pdatt:[A-Za-z0-9_-]+/i.test(source)) {
    errors.push(`${relative} must obtain attendance QR payloads from a protected MAESTRO_ variable.`);
  }
}

const workflowDocument = parseDocument(read('.eas/workflows/release-hermes-smoke.yml'));
if (workflowDocument.errors.length) {
  errors.push(`Release workflow is not valid YAML: ${workflowDocument.errors[0].message}`);
} else {
  const workflow = workflowDocument.toJS();
  const maestroJobs = Object.values(workflow.jobs || {}).filter((job) => job?.type === 'maestro');
  if (maestroJobs.length !== 3) {
    errors.push('Release workflow must contain Android, iOS, and Android-offline Maestro gates.');
  }
  for (const job of maestroJobs) {
    if (String(job.params?.maestro_version) !== expectedMaestroVersion) {
      errors.push('Every Maestro release job must pin the reviewed CLI version.');
    }
    if (job.params?.retries !== 1 || job.params?.retry_failed_only !== true) {
      errors.push('Every Maestro release job must use one failed-flow-only retry.');
    }
    if (job.params?.record_screen !== false) {
      errors.push('Credentialed release journeys must not upload screen recordings.');
    }
    if (!job.hooks?.before_maestro_tests) {
      errors.push('Every Maestro release job must validate the synthetic staging boundary first.');
    }
  }
  for (const jobId of ['test_android', 'test_ios']) {
    const flows = workflow.jobs?.[jobId]?.params?.flow_path;
    if (!hasExactMembers(flows, releaseHermesCoreFlows)) {
      errors.push(`${jobId} must run every reviewed cross-platform manager/passenger journey.`);
    }
  }
  if (
    workflow.jobs?.test_android_offline?.params?.flow_path
      !== '.maestro/flows/passenger-document-offline-android.yml'
  ) {
    errors.push('test_android_offline must remain isolated to the Android process-death cache flow.');
  }
}

function hasExactMembers(actual, expected) {
  return Array.isArray(actual)
    && actual.length === expected.length
    && expected.every((value) => actual.includes(value));
}

function normalizeShellCommand(value) {
  return typeof value === 'string'
    ? value.trim().replace(/\\\r?\n/g, ' ').replace(/\s+/g, ' ')
    : '';
}

function validateAttendanceFixtureBuildProfiles(configuration) {
  const profileErrors = [];
  const profiles = configuration?.build || {};
  if (
    configuration?.cli?.appVersionSource !== 'local'
    || configuration?.cli?.requireCommit !== true
    || profiles.production?.autoIncrement !== false
    || profiles['production-apk']?.autoIncrement != null
    || profiles['production-emulator-apk']?.autoIncrement != null
  ) {
    profileErrors.push('Android production profiles must require a clean committed source state and use explicit checked-in local versions with auto-increment disabled.');
  }
  const e2e = profiles['e2e-test'];
  if (
    e2e?.environment !== 'preview'
    || e2e?.withoutCredentials !== true
    || e2e?.env?.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE !== 'true'
    || !hasExactMembers(Object.keys(e2e?.env || {}), [
      'EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE',
    ])
  ) {
    profileErrors.push('The e2e-test profile must be an unsigned preview artifact with only the public attendance fixture flag enabled.');
  }
  if (profiles.production?.env?.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE !== 'false') {
    profileErrors.push('The production profile must explicitly disable the attendance fixture.');
  }
  if (profiles['production-apk']?.extends !== 'production') {
    profileErrors.push('The production-apk profile must inherit the fixture-disabled production profile.');
  }
  if (
    profiles.production?.android?.gradleCommand
      !== ':app:bundleRelease -PreactNativeArchitectures=armeabi-v7a,arm64-v8a,x86,x86_64'
  ) {
    profileErrors.push('The production AAB profile must use a highest-precedence Gradle project property for every reviewed Android ABI.');
  }
  if (
    profiles['production-apk']?.android?.gradleCommand
      !== ':app:assembleRelease -PreactNativeArchitectures=arm64-v8a'
  ) {
    profileErrors.push('The installable production APK profile must use a highest-precedence ARM64-only Gradle property.');
  }
  const emulatorProfile = profiles['production-emulator-apk'];
  if (
    emulatorProfile?.extends !== 'production'
    || emulatorProfile?.distribution !== 'internal'
    || emulatorProfile?.android?.buildType !== 'apk'
    || emulatorProfile?.withoutCredentials === true
    || emulatorProfile?.android?.gradleCommand
      !== ':app:assembleRelease -PreactNativeArchitectures=x86_64'
    || !hasExactMembers(Object.keys(emulatorProfile?.env || {}), [])
  ) {
    profileErrors.push('The signed production-config emulator profile must be a credentialed internal x86_64 APK that inherits production.');
  }
  for (const [profileName, profile] of Object.entries(profiles)) {
    const inlineKeys = Object.keys(profile?.env || {});
    if (inlineKeys.includes('ORG_GRADLE_PROJECT_reactNativeArchitectures')) {
      profileErrors.push(`${profileName} must not use the lower-precedence ORG_GRADLE_PROJECT architecture override.`);
    }
    if (inlineKeys.some((key) => key.startsWith('MAESTRO_'))) {
      profileErrors.push(`${profileName} must obtain protected MAESTRO_ values from its EAS environment.`);
    }
    if (
      profileName !== 'e2e-test'
      && profile?.env?.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE === 'true'
    ) {
      profileErrors.push(`${profileName} must not enable the preview attendance fixture.`);
    }
  }
  return profileErrors;
}

function validateProductionReleaseWorkflow(workflow) {
  const productionErrors = [];
  const jobs = workflow?.jobs || {};
  if (
    workflow?.defaults?.image !== 'sdk-57'
    || String(workflow?.defaults?.tools?.node) !== '20.19.4'
  ) {
    productionErrors.push('Production workflow must pin the reviewed SDK 57 image and Node 20.19.4 toolchain.');
  }
  const expectedJobIds = [
    'validate_production',
    'build_android_smoke',
    'test_android_release_hermes',
    'test_android_offline',
    'test_android_attendance',
    'build_android_signed_smoke',
    'verify_android_signed_smoke',
    'test_android_signed_public',
    'build_android',
    'verify_android_bundle',
    'approve_android_submission',
    'submit_android',
  ];
  if (!hasExactMembers(Object.keys(jobs), expectedJobIds)) {
    productionErrors.push('Production workflow must contain only the reviewed Android validation, smoke, build, approval, and submission jobs.');
  }

  for (const [jobId, job] of Object.entries(jobs)) {
    if (job?.if != null || job?.after != null || job?.continue_on_error != null) {
      productionErrors.push(`${jobId} must not conditionally skip or weaken a mandatory release gate.`);
    }
    if (
      job?.env != null
      && !['verify_android_signed_smoke', 'verify_android_bundle'].includes(jobId)
    ) {
      productionErrors.push(`${jobId} must consume protected EAS environment variables instead of inline workflow values.`);
    }
    if (job?.params?.platform === 'ios') {
      productionErrors.push('The production workflow must remain Android-only.');
    }
  }

  const validation = jobs.validate_production;
  const validationSteps = Array.isArray(validation?.steps) ? validation.steps : [];
  if (
    validation?.type != null
    || validation?.environment !== 'production'
    || validationSteps[0]?.uses !== 'eas/checkout'
    || validationSteps[1]?.uses !== 'eas/install_node_modules'
  ) {
    productionErrors.push('validate_production must be an EAS custom production job that checks out source and installs locked dependencies first.');
  }
  const requiredValidationCommands = [
    'npm run audit:runtime',
    'npm run config:validate',
    'npm run typecheck',
    'npm run lint',
    'npm run test:coverage',
    'npm run maintainability:check',
    'npm run e2e:contracts',
    'npm run release:preflight-android',
  ];
  for (const command of requiredValidationCommands) {
    if (!validationSteps.some((step) => step?.run?.trim() === command)) {
      productionErrors.push(`validate_production must run the mandatory gate: ${command}.`);
    }
  }
  if (validationSteps.some((step) => step?.if != null || step?.continue_on_error != null)) {
    productionErrors.push('Production validation steps must be unconditional and fail closed.');
  }

  const smokeBuild = jobs.build_android_smoke;
  if (
    smokeBuild?.type !== 'build'
    || smokeBuild?.params?.platform !== 'android'
    || smokeBuild?.params?.profile !== 'e2e-test'
    || !hasExactMembers(smokeBuild?.needs, ['validate_production'])
  ) {
    productionErrors.push('build_android_smoke must build the reviewed Android e2e-test profile after production validation.');
  }

  const validateMaestroGate = (jobId, expectedNeeds, expectedFlows) => {
    const job = jobs[jobId];
    const actualFlows = Array.isArray(job?.params?.flow_path)
      ? job.params.flow_path
      : [job?.params?.flow_path].filter(Boolean);
    const beforeHooks = job?.hooks?.before_maestro_tests;
    if (
      job?.type !== 'maestro'
      || job?.environment !== 'preview'
      || job?.runs_on !== 'linux-large-nested-virtualization'
      || !hasExactMembers(job?.needs, expectedNeeds)
      || job?.params?.build_id !== '${{ needs.build_android_smoke.outputs.build_id }}'
      || !hasExactMembers(actualFlows, expectedFlows)
      || job?.params?.device_identifier !== 'pixel_6'
      || job?.params?.retries !== 1
      || job?.params?.retry_failed_only !== true
      || job?.params?.record_screen !== false
      || job?.params?.output_format !== 'junit'
      || String(job?.params?.maestro_version) !== expectedMaestroVersion
      || !Array.isArray(beforeHooks)
      || !beforeHooks.some((step) => step?.run?.trim() === 'node scripts/validate-maestro-environment.js')
    ) {
      productionErrors.push(`${jobId} must run the reviewed, privacy-safe Android Maestro gate against the exact smoke build.`);
    }
  };
  validateMaestroGate(
    'test_android_release_hermes',
    ['build_android_smoke'],
    [
      ...releaseHermesCoreFlows,
    ],
  );
  validateMaestroGate(
    'test_android_offline',
    ['build_android_smoke', 'test_android_release_hermes'],
    ['.maestro/flows/passenger-document-offline-android.yml'],
  );
  validateMaestroGate(
    'test_android_attendance',
    ['build_android_smoke', 'test_android_release_hermes'],
    ['.maestro/flows/coordinator-attendance-offline-android.yml'],
  );

  const signedSmokeBuild = jobs.build_android_signed_smoke;
  if (
    signedSmokeBuild?.type !== 'build'
    || signedSmokeBuild?.params?.platform !== 'android'
    || signedSmokeBuild?.params?.profile !== 'production-emulator-apk'
    || !hasExactMembers(signedSmokeBuild?.needs, [
      'validate_production',
      'test_android_release_hermes',
      'test_android_offline',
      'test_android_attendance',
    ])
  ) {
    productionErrors.push('build_android_signed_smoke must build the signed production-config x86_64 profile after every synthetic functional gate.');
  }

  const validateArtifactVerificationJob = ({
    jobId,
    expectedBuildJob,
    expectedDownloadId,
    expectedExtension,
    expectedReceipt,
    expectedArtifactName,
    expectedCommand,
    expectedVerificationEnv,
    expectedPreparationCommand,
  }) => {
    const job = jobs[jobId];
    const steps = Array.isArray(job?.steps) ? job.steps : [];
    const download = steps[1];
    const preparation = expectedPreparationCommand ? steps[2] : null;
    const verification = expectedPreparationCommand ? steps[3] : steps[2];
    const upload = expectedPreparationCommand ? steps[4] : steps[3];
    const verificationEnv = job?.env || {};
    if (
      job?.type != null
      || job?.environment !== 'preview'
      || !hasExactMembers(job?.needs, [expectedBuildJob])
      || steps.length !== (expectedPreparationCommand ? 5 : 4)
      || steps[0]?.uses !== 'eas/checkout'
      || download?.uses !== 'eas/download_build'
      || download?.id !== expectedDownloadId
      || download?.with?.build_id !== `\${{ needs.${expectedBuildJob}.outputs.build_id }}`
      || !hasExactMembers(download?.with?.extensions, [expectedExtension])
      || (expectedPreparationCommand
        && (
          preparation?.name !== 'Fetch and pin official bundletool'
          || normalizeShellCommand(preparation?.run)
            !== normalizeShellCommand(expectedPreparationCommand)
          || preparation?.env != null
        ))
      || !hasExactMembers(Object.keys(verificationEnv), Object.keys(expectedVerificationEnv))
      || Object.entries(expectedVerificationEnv).some(
        ([name, value]) => verificationEnv[name] !== value,
      )
      || verification?.env != null
      || normalizeShellCommand(verification?.run) !== normalizeShellCommand(expectedCommand)
      || upload?.uses !== 'eas/upload_artifact'
      || upload?.with?.type !== 'other'
      || upload?.with?.name !== expectedArtifactName
      || upload?.with?.path !== expectedReceipt
      || steps.some((step) => step?.if != null || step?.continue_on_error != null)
    ) {
      productionErrors.push(`${jobId} must download, verify, and preserve a receipt for the exact signed build without a bypass.`);
    }
    return verification;
  };

  validateArtifactVerificationJob({
    jobId: 'verify_android_signed_smoke',
    expectedBuildJob: 'build_android_signed_smoke',
    expectedDownloadId: 'download_signed_apk',
    expectedExtension: 'apk',
    expectedReceipt: 'android-production-apk-verification.json',
    expectedArtifactName: 'android-production-apk-verification',
    expectedVerificationEnv: {
      GC_VERIFY_BUILD_ID: '${{ needs.build_android_signed_smoke.outputs.build_id }}',
      GC_VERIFY_GIT_COMMIT_HASH: '${{ needs.build_android_signed_smoke.outputs.git_commit_hash }}',
      GC_VERIFY_SOURCE_FINGERPRINT_HASH: '${{ needs.build_android_signed_smoke.outputs.fingerprint_hash }}',
      GC_VERIFY_APP_VERSION: '${{ needs.build_android_signed_smoke.outputs.app_version }}',
      GC_VERIFY_APP_BUILD_VERSION: '${{ needs.build_android_signed_smoke.outputs.app_build_version }}',
    },
    expectedCommand: [
      'set -eu',
      'verifier_home="$(mktemp -d)"',
      'env -i',
      'PATH="$PATH"',
      'HOME="$verifier_home"',
      'LANG="${LANG:-C.UTF-8}"',
      'ANDROID_HOME="${ANDROID_HOME:-}"',
      'ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-}"',
      'JAVA_HOME="${JAVA_HOME:-}"',
      'GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS="$GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS"',
      'node scripts/verify-android-artifact.js',
      '"${{ steps.download_signed_apk.outputs.artifact_path }}"',
      'android-production-apk-verification.json',
      '"$GC_VERIFY_BUILD_ID"',
      '"$GC_VERIFY_GIT_COMMIT_HASH"',
      '"$GC_VERIFY_SOURCE_FINGERPRINT_HASH"',
      'x86_64',
      '"$GC_VERIFY_APP_VERSION"',
      '"$GC_VERIFY_APP_BUILD_VERSION"',
    ].join(' '),
  });

  const signedPublicTest = jobs.test_android_signed_public;
  const signedPublicFlows = Array.isArray(signedPublicTest?.params?.flow_path)
    ? signedPublicTest.params.flow_path
    : [signedPublicTest?.params?.flow_path].filter(Boolean);
  if (
    signedPublicTest?.type !== 'maestro'
    || signedPublicTest?.environment !== 'production'
    || signedPublicTest?.runs_on !== 'linux-large-nested-virtualization'
    || !hasExactMembers(signedPublicTest?.needs, [
      'build_android_signed_smoke',
      'verify_android_signed_smoke',
    ])
    || signedPublicTest?.params?.build_id !== '${{ needs.build_android_signed_smoke.outputs.build_id }}'
    || !hasExactMembers(signedPublicFlows, ['.maestro/release-hermes-auth-smoke.yml'])
    || signedPublicTest?.params?.device_identifier !== 'pixel_6'
    || signedPublicTest?.params?.retries !== 1
    || signedPublicTest?.params?.retry_failed_only !== true
    || signedPublicTest?.params?.record_screen !== false
    || signedPublicTest?.params?.output_format !== 'junit'
    || String(signedPublicTest?.params?.maestro_version) !== expectedMaestroVersion
    || signedPublicTest?.hooks != null
  ) {
    productionErrors.push('test_android_signed_public must run only the credential-free public shell against the exact verified signed production APK.');
  }

  const productionBuild = jobs.build_android;
  if (
    productionBuild?.type !== 'build'
    || productionBuild?.params?.platform !== 'android'
    || productionBuild?.params?.profile !== 'production'
    || !hasExactMembers(productionBuild?.needs, [
      'validate_production',
      'test_android_release_hermes',
      'test_android_offline',
      'test_android_attendance',
      'verify_android_signed_smoke',
      'test_android_signed_public',
    ])
  ) {
    productionErrors.push('build_android must build the signed production profile only after every mandatory Android gate passes.');
  }

  validateArtifactVerificationJob({
    jobId: 'verify_android_bundle',
    expectedBuildJob: 'build_android',
    expectedDownloadId: 'download_production_aab',
    expectedExtension: 'aab',
    expectedReceipt: 'android-production-aab-verification.json',
    expectedArtifactName: 'android-production-aab-verification',
    expectedPreparationCommand: [
      'set -eu',
      'bundletool_directory="$(mktemp -d)"',
      'bundletool_path="$bundletool_directory/bundletool-all-1.18.3.jar"',
      'curl --fail --location --silent --show-error',
      'https://github.com/google/bundletool/releases/download/1.18.3/bundletool-all-1.18.3.jar',
      '--output "$bundletool_path"',
      'bundletool_sha256="$(sha256sum "$bundletool_path" | awk \'{print toupper($1)}\')"',
      'test "$bundletool_sha256" = "A099CFA1543F55593BC2ED16A70A7C67FE54B1747BB7301F37FDFD6D91028E29"',
      'set-env GC_ANDROID_BUNDLETOOL_JAR_PATH "$bundletool_path"',
    ].join(' '),
    expectedVerificationEnv: {
      GC_VERIFY_BUILD_ID: '${{ needs.build_android.outputs.build_id }}',
      GC_VERIFY_GIT_COMMIT_HASH: '${{ needs.build_android.outputs.git_commit_hash }}',
      GC_VERIFY_SOURCE_FINGERPRINT_HASH: '${{ needs.build_android.outputs.fingerprint_hash }}',
      GC_VERIFY_APP_IDENTIFIER: '${{ needs.build_android.outputs.app_identifier }}',
      GC_VERIFY_APP_VERSION: '${{ needs.build_android.outputs.app_version }}',
      GC_VERIFY_APP_BUILD_VERSION: '${{ needs.build_android.outputs.app_build_version }}',
    },
    expectedCommand: [
      'set -eu',
      'verifier_home="$(mktemp -d)"',
      'env -i',
      'PATH="$PATH"',
      'HOME="$verifier_home"',
      'LANG="${LANG:-C.UTF-8}"',
      'JAVA_HOME="${JAVA_HOME:-}"',
      'GC_ANDROID_BUNDLETOOL_JAR_PATH="$GC_ANDROID_BUNDLETOOL_JAR_PATH"',
      'GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS="$GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS"',
      'node scripts/verify-android-bundle.js',
      '"${{ steps.download_production_aab.outputs.artifact_path }}"',
      'android-production-aab-verification.json',
      '"$GC_VERIFY_BUILD_ID"',
      '"$GC_VERIFY_GIT_COMMIT_HASH"',
      '"$GC_VERIFY_SOURCE_FINGERPRINT_HASH"',
      '"$GC_VERIFY_APP_IDENTIFIER"',
      '"$GC_VERIFY_APP_VERSION"',
      '"$GC_VERIFY_APP_BUILD_VERSION"',
    ].join(' '),
  });
  if (
    jobs.verify_android_bundle?.env?.GC_VERIFY_APP_IDENTIFIER
      !== '${{ needs.build_android.outputs.app_identifier }}'
  ) {
    productionErrors.push('verify_android_bundle must bind verification to the EAS production app identifier.');
  }

  const approval = jobs.approve_android_submission;
  if (
    approval?.type !== 'require-approval'
    || !hasExactMembers(approval?.needs, ['build_android', 'verify_android_bundle'])
  ) {
    productionErrors.push('Android store submission must require human approval after the verified signed production build.');
  }

  const submission = jobs.submit_android;
  if (
    submission?.type !== 'submit'
    || submission?.params?.profile !== 'production'
    || submission?.params?.build_id !== '${{ needs.build_android.outputs.build_id }}'
    || !hasExactMembers(submission?.needs, [
      'build_android',
      'verify_android_bundle',
      'approve_android_submission',
    ])
  ) {
    productionErrors.push('submit_android must submit only the exact human-approved Android production build.');
  }

  return productionErrors;
}

function validateAndroidGradleWrapperPluginSource(appConfigSource) {
  const pluginMatches = typeof appConfigSource === 'string'
    ? appConfigSource.match(/["']\.\/plugins\/with-android-gradle-wrapper-integrity["']/g) || []
    : [];
  return pluginMatches.length === 1
    ? []
    : ['Android clean prebuild must register exactly one reviewed Gradle wrapper integrity plugin.'];
}

function validateAndroidLocalReleaseScripts(packageDocument) {
  const releaseErrors = [];
  if (
    packageDocument?.scripts?.['release:verify-android-apk']
      !== 'node scripts/verify-android-artifact.js'
    || packageDocument?.scripts?.['release:verify-android-aab']
      !== 'node scripts/verify-android-bundle.js'
  ) {
    releaseErrors.push('Android release verifier commands must point to the reviewed APK and AAB verifiers.');
  }
  const arm64GradleScript = String(
    packageDocument?.scripts?.['android:gradle:apk:arm64'] || '',
  );
  const arm64GradleChain = String(
    packageDocument?.scripts?.['android:gradle:apk:arm64:chain'] || '',
  );
  const emulatorGradleScript = String(
    packageDocument?.scripts?.['android:gradle:apk:emulator'] || '',
  );
  const emulatorGradleChain = String(
    packageDocument?.scripts?.['android:gradle:apk:emulator:chain'] || '',
  );
  const aabGradleScript = String(
    packageDocument?.scripts?.['android:gradle:aab'] || '',
  );
  if (
    arm64GradleScript
      !== 'cross-env NODE_ENV=production npm run android:gradle:apk:arm64:chain'
    || !arm64GradleChain.startsWith('android\\gradlew.bat -p android --no-parallel ')
    || !arm64GradleChain.includes('"-PreactNativeArchitectures=arm64-v8a"')
    || arm64GradleChain.includes('ORG_GRADLE_PROJECT_reactNativeArchitectures')
    || !arm64GradleChain.endsWith(
      '&& node scripts/stage-android-apk.js stage android/app/build/outputs/apk/release/app-release.apk outputs/android-staging/app-release-arm64-v8a.apk arm64-v8a',
    )
    || emulatorGradleScript
      !== 'cross-env NODE_ENV=production npm run android:gradle:apk:emulator:chain'
    || !emulatorGradleChain.startsWith('android\\gradlew.bat -p android --no-parallel ')
    || !emulatorGradleChain.includes('"-PreactNativeArchitectures=x86_64"')
    || emulatorGradleChain.includes('ORG_GRADLE_PROJECT_reactNativeArchitectures')
    || !emulatorGradleChain.endsWith(
      '&& node scripts/stage-android-apk.js stage android/app/build/outputs/apk/release/app-release.apk outputs/android-staging/app-release-x86_64.apk x86_64',
    )
    || !aabGradleScript.startsWith('cross-env NODE_ENV=production ')
    || !aabGradleScript.startsWith(
      'cross-env NODE_ENV=production android\\gradlew.bat -p android --no-parallel ',
    )
    || !aabGradleScript.includes(
      '"-PreactNativeArchitectures=armeabi-v7a,arm64-v8a,x86,x86_64"',
    )
    || aabGradleScript.includes('ORG_GRADLE_PROJECT_reactNativeArchitectures')
    || !String(packageDocument?.scripts?.['release:prepare-android'] || '')
      .includes('cross-env NODE_ENV=production GC_VALIDATE_ANDROID_PUSH=true expo prebuild')
    || packageDocument?.scripts?.['release:stage-android-apk']
      !== 'cross-env NODE_ENV=production node scripts/stage-android-apk.js'
    || packageDocument?.scripts?.['release:package-local-android-sideload']
      !== 'cross-env NODE_ENV=production node scripts/package-local-android-sideload.js'
    || packageDocument?.scripts?.['release:package-local-android-bundle']
      !== 'cross-env NODE_ENV=production node scripts/package-local-android-bundle.js'
    || packageDocument?.scripts?.['release:verify-staged-android-apk:arm64']
      !== 'cross-env NODE_ENV=production node scripts/stage-android-apk.js verify outputs/android-staging/app-release-arm64-v8a.apk arm64-v8a'
    || packageDocument?.scripts?.['release:verify-staged-android-apk:emulator']
      !== 'cross-env NODE_ENV=production node scripts/stage-android-apk.js verify outputs/android-staging/app-release-x86_64.apk x86_64'
    || packageDocument?.scripts?.['release:verify-android-size']
      !== 'node scripts/verify-android-binary-size.mjs outputs/android-staging/app-release-arm64-v8a.apk android/app/build/outputs/bundle/release/app-release.aab'
    || packageDocument?.scripts?.['android:release-artifacts']
      !== 'npm run release:prepare-android && npm run android:gradle:apk:arm64 && npm run android:gradle:aab && npm run release:verify-staged-android-apk:arm64 && npm run release:verify-android-size'
  ) {
    releaseErrors.push('Android local release scripts must preserve NODE_ENV=production and keep lane evidence under outputs/android-staging outside disposable Gradle build outputs across generation, Gradle, staging, packaging, lane re-verification, and the all-ABI size gates.');
  }
  return releaseErrors;
}

const productionWorkflowDocument = parseDocument(read('.eas/workflows/production-release.yml'));
if (productionWorkflowDocument.errors.length) {
  errors.push(`Production workflow is not valid YAML: ${productionWorkflowDocument.errors[0].message}`);
} else {
  const workflow = productionWorkflowDocument.toJS();
  errors.push(...validateProductionReleaseWorkflow(workflow));
}

const easConfiguration = JSON.parse(read('eas.json'));
errors.push(...validateAttendanceFixtureBuildProfiles(easConfiguration));

const packageDocument = JSON.parse(read('package.json'));
errors.push(...validateAndroidGradleWrapperPluginSource(read('app.config.ts')));
const expectedAndroidPreflight = [
  'npm run dependencies:check',
  'npm run release:validate-env',
  'npm run release:validate-android-push',
  'npm run release:validate-android-distribution',
  'npm run release:validate-links:android',
];
const actualAndroidPreflight = String(
  packageDocument?.scripts?.['release:preflight-android'] || '',
).split('&&').map((command) => command.trim()).filter(Boolean);
if (JSON.stringify(actualAndroidPreflight) !== JSON.stringify(expectedAndroidPreflight)) {
  errors.push('Android production preflight must run the reviewed dependency, environment, push, distribution-signer, and live-link gates in order.');
}
errors.push(...validateAndroidLocalReleaseScripts(packageDocument));

if (errors.length) throw new Error(`Maestro workspace contract failed:\n- ${errors.join('\n- ')}`);
process.stdout.write('Maestro workspace and guarded release workflow contracts passed.\n');

module.exports = {
  validateAndroidGradleWrapperPluginSource,
  validateAndroidLocalReleaseScripts,
  validateAttendanceFixtureBuildProfiles,
  validateProductionReleaseWorkflow,
};
