import { z } from "zod";

// Production CSP forbids string evaluation, including Zod's caught JIT probe.
// Configure before app schemas are constructed so validation never attempts it.
z.config({ jitless: true });

export { z };
