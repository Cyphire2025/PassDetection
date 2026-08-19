'use strict';

const {
  validateObservabilityBuildEnvironment,
  validateProductionPublicEnvironment,
} = require('./production-public-env');

try {
  validateProductionPublicEnvironment(process.env);
  validateObservabilityBuildEnvironment(process.env);
  console.log('Production public and protected build environments passed.');
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
