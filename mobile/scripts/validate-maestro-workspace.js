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
}

if (errors.length) throw new Error(`Maestro workspace contract failed:\n- ${errors.join('\n- ')}`);
process.stdout.write('Maestro workspace and release workflow contracts passed.\n');
