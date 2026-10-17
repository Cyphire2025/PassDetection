/** Keep every part of long replies while bounding each speech request. */
export function speechChunks(markdown: string): string[] {
  let remaining = markdown.replace(/[#*`|]/g, "").trim();
  const chunks: string[] = [];
  while (remaining) {
    // A UTF-8 byte bound also bounds worst-case tokens for Hindi, CJK and emoji.
    let end = 0; let bytes = 0;
    for (const character of remaining) {
      const code = character.codePointAt(0)!;
      const size = code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
      if (bytes + size > 1700) break;
      bytes += size; end += character.length;
    }
    if (end < remaining.length) {
      const boundary = Math.max(remaining.lastIndexOf(". ", end - 1), remaining.lastIndexOf("\n", end - 1), remaining.lastIndexOf(" ", end - 1));
      if (boundary > end * .6) end = boundary + 1;
      const code = remaining.charCodeAt(end - 1);
      if (code >= 0xd800 && code <= 0xdbff) end--;
    }
    chunks.push(remaining.slice(0, end).trim());
    remaining = remaining.slice(end).trimStart();
  }
  return chunks;
}
