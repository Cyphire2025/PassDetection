export interface WhatsAppTextSelection {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

export interface WhatsAppTextSegment {
  text: string;
  bold: boolean;
}

function hasOpenBoldMarker(value: string, caret: number) {
  let markerCount = 0;
  for (let index = 0; index < caret; index += 1) {
    if (value[index] === "*" && value[index - 1] !== "\\") {
      markerCount += 1;
    }
  }
  return markerCount % 2 === 1;
}

export function toggleWhatsAppBold(
  value: string,
  selectionStart: number,
  selectionEnd: number,
): WhatsAppTextSelection {
  const start = Math.max(0, Math.min(selectionStart, value.length));
  const end = Math.max(start, Math.min(selectionEnd, value.length));

  if (start !== end) {
    if (start > 0 && value[start - 1] === "*" && value[end] === "*") {
      return {
        value: `${value.slice(0, start - 1)}${value.slice(start, end)}${value.slice(end + 1)}`,
        selectionStart: start - 1,
        selectionEnd: end - 1,
      };
    }
    if (value[start] === "*" && value[end - 1] === "*" && end - start > 1) {
      return {
        value: `${value.slice(0, start)}${value.slice(start + 1, end - 1)}${value.slice(end)}`,
        selectionStart: start,
        selectionEnd: end - 2,
      };
    }
    return {
      value: `${value.slice(0, start)}*${value.slice(start, end)}*${value.slice(end)}`,
      selectionStart: start + 1,
      selectionEnd: end + 1,
    };
  }

  if (value[start] === "*" && hasOpenBoldMarker(value, start)) {
    return {
      value,
      selectionStart: start + 1,
      selectionEnd: start + 1,
    };
  }

  return {
    value: `${value.slice(0, start)}**${value.slice(start)}`,
    selectionStart: start + 1,
    selectionEnd: start + 1,
  };
}

export function parseWhatsAppBoldSegments(value: string): WhatsAppTextSegment[] {
  const segments: WhatsAppTextSegment[] = [];
  const pattern = /\*([^*\n]+)\*/g;
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({ text: value.slice(cursor, index), bold: false });
    }
    segments.push({ text: match[1], bold: true });
    cursor = index + match[0].length;
  }
  if (cursor < value.length) {
    segments.push({ text: value.slice(cursor), bold: false });
  }
  return segments.length > 0 ? segments : [{ text: value, bold: false }];
}
