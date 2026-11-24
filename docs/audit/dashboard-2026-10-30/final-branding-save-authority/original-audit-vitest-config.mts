import { resolve } from "node:path";
import base from "../../frontend/vitest.config.mts";
export default { ...base, root: resolve(import.meta.dirname, "../../frontend"), envDir: false };
