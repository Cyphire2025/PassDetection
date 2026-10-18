import type { SculptureAppearance } from "./types";
const TAU = Math.PI * 2;
const random = (value: number) => { const n = Math.sin(value * 127.1 + 311.7) * 43758.5453; return n - Math.floor(n); };
function emoji(ctx: CanvasRenderingContext2D, name: string) {
    ctx.translate(320, 128);
    ctx.lineWidth = 8;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (name === "heart") {
        ctx.beginPath();
        ctx.moveTo(0, 79);
        ctx.bezierCurveTo(-150, -20, -72, -120, 0, -48);
        ctx.bezierCurveTo(72, -120, 150, -20, 0, 79);
        ctx.fill();
    }
    else if (name === "plane") {
        ctx.beginPath();
        [[-13, -98], [12, -98], [24, -25], [110, 29], [110, 46], [21, 14], [15, 75], [48, 94], [48, 105], [0, 94], [-48, 105], [-48, 94], [-15, 75], [-21, 14], [-110, 46], [-110, 29], [-24, -25]].forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
        ctx.closePath();
        ctx.fill();
    }
    else if (name === "star") {
        ctx.beginPath();
        for (let i = 0; i < 10; i++) {
            const angle = i * TAU / 10 - Math.PI / 2, radius = i % 2 ? 43 : 105;
            const x = Math.cos(angle) * radius, y = Math.sin(angle) * radius;
            if (i)
                ctx.lineTo(x, y);
            else
                ctx.moveTo(x, y);
        }
        ctx.closePath();
        ctx.fill();
    }
    else {
        ctx.beginPath();
        ctx.arc(0, 0, 100, 0, TAU);
        ctx.stroke();
        if (name === "globe") {
            ctx.beginPath();
            ctx.ellipse(0, 0, 42, 100, 0, 0, TAU);
            ctx.stroke();
            for (const y of [-42, 0, 42]) {
                ctx.beginPath();
                ctx.ellipse(0, y, Math.sqrt(10000 - y * y), 18, 0, 0, TAU);
                ctx.stroke();
            }
        }
        else {
            for (const x of [-33, 33]) {
                ctx.beginPath();
                ctx.arc(x, -24, 7, 0, TAU);
                ctx.fill();
            }
            ctx.beginPath();
            ctx.arc(0, 5, 55, .16, Math.PI - .16);
            ctx.stroke();
        }
    }
}
function mask(selection: SculptureAppearance, logo: HTMLImageElement | null): number[] {
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 256;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#fff";
    if (selection.mode === "emoji")
        emoji(ctx, selection.emoji);
    else if (selection.mode === "logo" && logo) {
        ctx.drawImage(logo, 0, 0, 640, 256);
        const pixels = ctx.getImageData(0, 0, 640, 256).data;
        let left = 640, top = 256, right = 0, bottom = 0;
        for (let y = 0; y < 256; y++)
            for (let x = 0; x < 640; x++)
                if (pixels[(y * 640 + x) * 4 + 3] > 100) {
                    left = Math.min(left, x);
                    top = Math.min(top, y);
                    right = Math.max(right, x);
                    bottom = Math.max(bottom, y);
                }
        ctx.clearRect(0, 0, 640, 256);
        const sw = Math.max(1, right - left + 1) * logo.naturalWidth / 640, sh = Math.max(1, bottom - top + 1) * logo.naturalHeight / 256;
        const scale = Math.min(590 / sw, 228 / sh);
        ctx.drawImage(logo, left * logo.naturalWidth / 640, top * logo.naturalHeight / 256, sw, sh, (640 - sw * scale) / 2, (256 - sh * scale) / 2, sw * scale, sh * scale);
    }
    else {
        const text = selection.mode === "logo" ? "gc ↗" : selection.text.trim() || "Global Connects";
        ctx.font = "600 118px Arial, sans-serif";
        const width = ctx.measureText(text).width;
        ctx.font = `600 ${Math.min(118, 118 * 590 / Math.max(1, width))}px Arial, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, 320, 136);
    }
    const data = ctx.getImageData(0, 0, 640, 256).data, points: number[] = [];
    for (let y = 0; y < 256; y += 2)
        for (let x = 0; x < 640; x += 2)
            if (data[(y * 640 + x) * 4 + 3] > 100)
                points.push(x, y);
    return points;
}
function face(seed: number): [
    number,
    number,
    number,
    number
] {
    const type = random(seed + 3), a = random(seed + 7) * TAU, t = random(seed + 13), side = random(seed + 19) > .5 ? 1 : -1;
    if (type < .2)
        return [.26 * Math.cos(a), .85 * Math.sin(a), .04, Math.sin(a) > .5 ? .12 : 0];
    if (type < .34)
        return [side * .108 + .061 * Math.cos(a), -.18 + .047 * Math.sin(a), .18, 0];
    if (type < .40)
        return [side * .108 + .012 * Math.cos(a), -.18 + .03 * Math.sin(a), .20, 0];
    if (type < .49)
        return [side * (.055 + t * .108), -.30 - Math.sin(t * Math.PI) * .04, .16, 0];
    if (type < .61)
        return type < .58
            ? [side * (.012 + Math.sin(t * Math.PI) * .012), -.13 + t * .32, .19 + Math.sin(t * Math.PI) * .12, 0]
            : [.036 * Math.cos(a), .20 + .025 * Math.sin(a), .23, 0];
    if (type < .75)
        return [.093 * Math.cos(a), .36 + .055 * Math.sin(a), .19, Math.sin(a) > 0 ? 1 : -.18];
    let radius = Math.sqrt(t), x = Math.cos(a) * radius, y = Math.sin(a) * radius;
    // Bounded rejection leaves clear eyes and lips without artificial cheek stripes.
    for (let attempt = 0; attempt < 8; attempt++) {
        const eye = ((Math.abs(x) - .44) / .29) ** 2 + ((y + .22) / .11) ** 2;
        const mouth = (x / .42) ** 2 + ((y - .44) / .13) ** 2;
        if (eye > 1.3 && mouth > 1.3)
            break;
        const angle = random(seed + attempt * 13 + 51) * TAU;
        radius = Math.sqrt(random(seed + attempt * 17 + 71));
        x = Math.cos(angle) * radius;
        y = Math.sin(angle) * radius;
    }
    return [x * .245, y * .81, Math.sqrt(Math.max(0, 1 - radius * radius)) * .14, y > .5 ? .1 : 0];
}
export function morphTargets(selection: SculptureAppearance, count: number, capacity: number, logo: HTMLImageElement | null): Float32Array {
    const result = new Float32Array(capacity * 4), points = selection.mode === "face" ? [] : mask(selection, logo);
    for (let i = 0; i < count; i++) {
        const index = i * 4, seed = i * .61803398875;
        if (selection.mode === "face")
            result.set(face(seed), index);
        else {
            const sample = Math.floor(random(seed + 1) * Math.max(1, points.length / 2)) * 2;
            result[index] = ((points[sample] ?? 320) + (random(seed + 9) - .5) * 2) / 320 - 1;
            result[index + 1] = ((points[sample + 1] ?? 128) + (random(seed + 11) - .5) * 2) / 128 - 1;
            result[index + 2] = (random(seed + 15) - .5) * .035;
        }
    }
    return result;
}
