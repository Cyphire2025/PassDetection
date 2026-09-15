const { withEntitlementsPlist } = require('expo/config-plugins');

/** Explicit personal-team testing lane; leave every unrelated entitlement intact. */
module.exports = function withIosPushCapability(config, { enabled = true } = {}) {
  return withEntitlementsPlist(config, (mod) => {
    if (!enabled) delete mod.modResults['aps-environment'];
    return mod;
  });
};
