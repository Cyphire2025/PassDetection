'use strict';

const { spawnSync } = require('node:child_process');

const ENFORCED_SEVERITIES = new Set(['high', 'critical']);

function collectAdvisoryUrls(vulnerabilityName, vulnerabilities, visited = new Set()) {
  if (visited.has(vulnerabilityName)) {
    return new Set();
  }
  visited.add(vulnerabilityName);

  const vulnerability = vulnerabilities[vulnerabilityName];
  if (!vulnerability || !Array.isArray(vulnerability.via)) {
    return new Set();
  }

  const urls = new Set();
  for (const cause of vulnerability.via) {
    if (typeof cause === 'string') {
      for (const url of collectAdvisoryUrls(cause, vulnerabilities, visited)) {
        urls.add(url);
      }
    } else if (cause && typeof cause.url === 'string') {
      urls.add(cause.url);
    }
  }
  return urls;
}

function findUnexpectedVulnerabilities(report) {
  const vulnerabilities = report?.vulnerabilities ?? {};
  const unexpected = [];

  for (const [name, vulnerability] of Object.entries(vulnerabilities)) {
    if (!ENFORCED_SEVERITIES.has(vulnerability?.severity)) {
      continue;
    }

    const advisoryUrls = [...collectAdvisoryUrls(name, vulnerabilities)];
    unexpected.push({ name, advisoryUrls });
  }

  return unexpected;
}

function main() {
  const npmArguments = ['audit', '--omit=dev', '--json'];
  const npmCli = process.env.npm_execpath;
  const executable = npmCli ? process.execPath : 'npm';
  const argumentsForProcess = npmCli
    ? [npmCli, ...npmArguments]
    : npmArguments;
  const result = spawnSync(
    executable,
    argumentsForProcess,
    {
      encoding: 'utf8',
      env: {
        ...process.env,
        npm_config_update_notifier: 'false',
      },
      maxBuffer: 16 * 1024 * 1024,
    },
  );

  if (result.error) {
    throw result.error;
  }

  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch {
    throw new Error(
      `npm audit did not return valid JSON. ${result.stderr || result.stdout}`.trim(),
    );
  }
  if (report?.error) {
    throw new Error(
      `npm audit failed: ${report.error.summary || report.error.code || 'unknown registry error'}`,
    );
  }
  if (![0, 1].includes(result.status) || typeof report?.auditReportVersion !== 'number') {
    throw new Error(
      `npm audit could not be verified (exit ${String(result.status)}).`,
    );
  }

  const unexpected = findUnexpectedVulnerabilities(report);
  if (unexpected.length > 0) {
    const details = unexpected
      .map(({ name, advisoryUrls }) =>
        `- ${name}: ${advisoryUrls.join(', ') || 'no root advisory reported'}`,
      )
      .join('\n');
    throw new Error(`Unexpected high/critical runtime audit findings:\n${details}`);
  }

  console.log('Runtime audit passed with no high or critical findings.');
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}

module.exports = {
  collectAdvisoryUrls,
  findUnexpectedVulnerabilities,
};
