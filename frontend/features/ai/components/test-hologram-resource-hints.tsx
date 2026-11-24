import landscapeManifest from "../../../public/ai/test-landscape/compact-v1.json";

/** Public scenery can download alongside session checks; account data cannot. */
export function HologramResourceHints() {
  return Object.values(landscapeManifest).map(({ file }) =>
    <link key={file} rel="preload" href={`/ai/test-landscape/${file}`} as="fetch" crossOrigin="anonymous" fetchPriority="low" />);
}
