import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils.js';
import { base64 } from '@scure/base';

function pdfText(value: string): string {
  return value.replace(/[^\x20-\x7e]/g, ' ').replace(/[\\()]/g, '\\$&');
}

/** Small, valid PDFs embedded entirely in the app; no real travel records. */
export function demoDocumentContent(title: string) {
  const lines = [
    'GLOBAL CONNECT TRAVELS', title,
    'SAMPLE DOCUMENT - NOT VALID FOR TRAVEL',
    'Singapore Discovery - demonstration trip',
    'Traveller: Demo Passenger',
    'Hotel: Marina Bay Grand Hotel - sample room 1208',
    'Meeting point: Terminal 3, Door 6 - sample itinerary',
    'Keep your documents and personal QR ready at reporting.',
    'For assistance, speak to your assigned trip coordinator.',
    'All names, assignments and travel records here are sample data.',
    'This document is supplied by the app and works offline.',
  ];
  const stream = `BT /F1 12 Tf 48 790 Td 22 TL\n${lines.map((line, i) => `${i ? 'T* ' : ''}(${pdfText(line)}) Tj`).join('\n')}\nET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  for (const [i, object] of objects.entries()) {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = pdf.length;
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map((n) => `${String(n).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  const bytes = utf8ToBytes(pdf);
  return { uri: `data:application/pdf;base64,${base64.encode(bytes)}`, size: bytes.length, checksum: bytesToHex(sha256(bytes)) };
}
