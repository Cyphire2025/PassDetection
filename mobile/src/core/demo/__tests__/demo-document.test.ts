import { base64 } from '@scure/base';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';
import { demoDocumentContent } from '../demo-document';

describe('embedded sample PDF', () => {
  it('has matching byte length, checksum and valid object/xref locations', () => {
    const document = demoDocumentContent('Passport (sample) \\ India · Preview');
    const bytes = base64.decode(document.uri.split(',')[1]!);
    const pdf = new TextDecoder().decode(bytes);
    expect(document.size).toBe(bytes.length);
    expect(document.checksum).toBe(bytesToHex(sha256(bytes)));
    expect(pdf).toContain('SAMPLE DOCUMENT - NOT VALID FOR TRAVEL');
    const xref = Number(/startxref\n(\d+)/.exec(pdf)![1]);
    expect(pdf.slice(xref)).toMatch(/^xref\n0 6\n/);
    const offsets = [...pdf.matchAll(/^(\d{10}) 00000 n /gm)];
    expect(offsets).toHaveLength(5);
    offsets.forEach((match, index) => expect(pdf.slice(Number(match[1]))).toMatch(new RegExp(`^${index + 1} 0 obj`)));
    const stream = /\/Length (\d+) >>\nstream\n([\s\S]*?)\nendstream/.exec(pdf)!;
    expect(stream[2]!.length).toBe(Number(stream[1]));
    expect(pdf).toContain('Passport \\(sample\\) \\\\ India');
  });
});
