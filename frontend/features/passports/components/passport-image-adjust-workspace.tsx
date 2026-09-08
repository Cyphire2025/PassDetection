"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from "react";
import { Crop, Grid2X2, Maximize, Minus, Plus, RotateCcw, RotateCw, SlidersHorizontal, Undo2 } from "lucide-react";
import { Button } from "@/components/ui";
import type { PassportImageCropRect } from "../api/passports.api";
import { MAX_FINE_ROTATION, MIN_FINE_ROTATION, rotatedImageBounds, type CropDragMode } from "../utils/passport-image-crop-geometry";
import { fitImagePreview, MAX_IMAGE_PREVIEW_ZOOM } from "../utils/passport-image-editor-viewport";

interface ImageAdjustWorkspaceProps {
  label: string;
  imageSize: { width: number; height: number };
  crop: PassportImageCropRect;
  fineRotation: number;
  sharpness: number;
  busy: boolean;
  hasChanges: boolean;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  stageRef: RefObject<HTMLDivElement | null>;
  onBeginDrag: (event: PointerEvent<HTMLElement>, mode: CropDragMode) => void;
  onMoveDrag: (event: PointerEvent<HTMLElement>) => void;
  onEndDrag: (event: PointerEvent<HTMLElement>) => void;
  onCropKeyDown: (event: KeyboardEvent<HTMLElement>, mode: CropDragMode) => void;
  onRotate: (direction: "left" | "right") => void;
  onFineRotation: (value: number) => void;
  onRotationInteraction: (active: boolean) => void;
  onSharpness: (value: number) => void;
  onFullImage: () => void;
  onUndo: () => void;
  onPreviewSizeChange: (maximumDimension: number) => void;
}

const toolButton = "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-600 hover:bg-white hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-35";

export function PassportImageAdjustWorkspace(props: ImageAdjustWorkspaceProps) {
  const { label, imageSize, crop, busy, canvasRef, stageRef } = props;
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);
  const [showGrid, setShowGrid] = useState(false);

  useEffect(() => {
    const node = viewportRef.current;
    if (!node) return;
    const measure = () => setViewport(current => {
      const width = Math.max(0, node.clientWidth - 48);
      const height = Math.max(0, node.clientHeight - 48);
      return width === current.width && height === current.height ? current : { width, height };
    });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const preview = fitImagePreview({
    imageWidth: imageSize.width, imageHeight: imageSize.height,
    viewportWidth: viewport.width, viewportHeight: viewport.height,
    rotationDegrees: crop.rotation_degrees, zoom,
  });
  const onPreviewSizeChange = props.onPreviewSizeChange;
  useEffect(() => {
    // Render more detail when enlarged, with a fixed ceiling on pixel work.
    const requested = Math.ceil(Math.max(preview.width, preview.height) * window.devicePixelRatio);
    onPreviewSizeChange(Math.min(2400, Math.max(1200, requested)));
  }, [onPreviewSizeChange, preview.width, preview.height]);
  const bounds = rotatedImageBounds(imageSize.width, imageSize.height, crop.rotation_degrees);
  const fit = () => {
    setZoom(1);
    viewportRef.current?.scrollTo({ left: 0, top: 0 });
  };
  const rotate = (direction: "left" | "right") => { fit(); props.onRotate(direction); };

  return (
    <div id="passport-image-adjust-panel" role="tabpanel" aria-labelledby="passport-image-adjust-tab"
      className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:grid lg:grid-cols-[minmax(0,1fr)_300px] lg:overflow-hidden">
      <section aria-label="Image preview" className="flex min-h-0 min-w-0 shrink-0 flex-col bg-slate-100">
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-200/80 px-3 py-2 sm:px-5">
          <span className="text-xs font-semibold text-slate-600">Preview</span>
          <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
            <button type="button" className={toolButton} aria-label="Zoom out preview" disabled={busy || preview.zoom <= 1}
              onClick={() => setZoom(Math.max(1, preview.zoom - 0.25))}><Minus className="h-4 w-4" /></button>
            <output aria-label="Preview zoom" className="w-10 text-center text-xs font-semibold tabular-nums text-slate-700">{Math.round(preview.zoom * 100)}%</output>
            <button type="button" className={toolButton} aria-label="Zoom in preview" disabled={busy || preview.zoom >= MAX_IMAGE_PREVIEW_ZOOM || preview.scale >= 1}
              onClick={() => setZoom(Math.min(MAX_IMAGE_PREVIEW_ZOOM, preview.zoom + 0.25))}><Plus className="h-4 w-4" /></button>
            <span className="mx-1 h-5 w-px bg-slate-200" />
            <button type="button" className={`${toolButton} w-auto gap-1.5 px-2`} onClick={fit} disabled={busy} aria-label="Fit image">
              <Maximize className="h-3.5 w-3.5" /> <span className="text-xs font-semibold">Fit</span>
            </button>
            <button type="button" className={`${toolButton} ${showGrid ? "bg-white text-blue-700" : ""}`} aria-label="Show crop grid" aria-pressed={showGrid}
              onClick={() => setShowGrid(current => !current)}><Grid2X2 className="h-4 w-4" /></button>
          </div>
        </div>
        <div ref={viewportRef} data-image-preview-viewport className="h-[clamp(220px,36dvh,380px)] min-h-0 shrink-0 overflow-auto overscroll-contain lg:h-auto lg:flex-1"
          style={{ backgroundImage: "radial-gradient(#cbd5e1 0.75px, transparent 0.75px)", backgroundSize: "16px 16px" }}>
          <div className="flex min-h-full min-w-full w-max items-center justify-center p-6">
            <div ref={stageRef} data-image-preview-stage className="relative shrink-0 select-none bg-white shadow-lg"
              style={{ width: preview.width, height: preview.height }}>
              <canvas ref={canvasRef} aria-label={`Editable ${label}`} className="block h-full w-full" />
              <CropShade crop={crop} />
              <div role="group" tabIndex={busy ? -1 : 0} aria-disabled={busy}
                aria-label="Crop frame. Use arrow keys to move it; hold Shift for larger steps."
                className={`absolute touch-none border-2 border-white shadow-[0_0_0_1px_rgba(15,23,42,0.8)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${busy ? "pointer-events-none" : "cursor-move"}`}
                style={{ left: percent(crop.x), top: percent(crop.y), width: percent(crop.width), height: percent(crop.height) }}
                onPointerDown={event => props.onBeginDrag(event, "move")} onPointerMove={props.onMoveDrag}
                onPointerUp={props.onEndDrag} onPointerCancel={props.onEndDrag}
                onKeyDown={event => props.onCropKeyDown(event, "move")}>
                {showGrid ? <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid grid-cols-3 grid-rows-3">
                  {Array.from({ length: 9 }, (_, index) => <span key={index} className="border-[0.5px] border-white/40" />)}
                </div> : null}
                {(["nw", "ne", "sw", "se"] as const).map(corner => <button key={corner} type="button" disabled={busy}
                  aria-label={`Resize crop from ${cornerLabel(corner)} corner`}
                  className={`absolute h-7 w-7 touch-none rounded-full border-2 border-white bg-black shadow-[0_0_0_2px_rgba(15,23,42,0.9),0_2px_8px_rgba(15,23,42,0.7)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${cornerClassName(corner)}`}
                  onPointerDown={event => props.onBeginDrag(event, corner)} onPointerMove={props.onMoveDrag}
                  onPointerUp={props.onEndDrag} onPointerCancel={props.onEndDrag}
                  onKeyDown={event => props.onCropKeyDown(event, corner)} />)}
              </div>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-1 border-t border-slate-200/80 px-4 py-2.5 text-[11px] text-slate-500">
          <span>Drag the corners to crop. Zoom to inspect details.</span>
          <span className="tabular-nums">{imageSize.width.toLocaleString()} × {imageSize.height.toLocaleString()} px</span>
        </div>
      </section>

      <aside aria-label="Image adjustments" className="min-h-0 shrink-0 border-t border-slate-200 bg-white lg:overflow-y-auto lg:border-l lg:border-t-0">
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-950">Adjustments</h3>
          <button type="button" disabled={busy || !props.hasChanges} onClick={() => { fit(); props.onUndo(); }}
            className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-blue-700 disabled:opacity-35">
            <Undo2 className="h-3.5 w-3.5" /> Undo changes
          </button>
        </div>
        <div className="space-y-4 p-4">
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Crop className="h-4 w-4 text-blue-600" /> Crop</h4>
              <button type="button" disabled={busy} onClick={props.onFullImage} className="text-xs font-semibold text-blue-600 hover:text-blue-800 disabled:opacity-40">Full image</button>
            </div>
            <p className="text-xs leading-5 text-slate-500">Keep the document edges inside the frame.</p>
            <div className="rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-500">
              Selection <span className="float-right font-medium tabular-nums text-slate-800">{Math.round(bounds.width * crop.width).toLocaleString()} × {Math.round(bounds.height * crop.height).toLocaleString()} px</span>
            </div>
          </section>
          <section className="space-y-3 border-t border-slate-100 pt-4">
            <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-800"><RotateCw className="h-4 w-4 text-blue-600" /> Rotate & straighten</h4>
            <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" size="sm" disabled={busy} onClick={() => rotate("left")} aria-label="Rotate left 90 degrees"><RotateCcw className="h-3.5 w-3.5" /> Left 90°</Button>
              <Button variant="outline" size="sm" disabled={busy} onClick={() => rotate("right")} aria-label="Rotate right 90 degrees"><RotateCw className="h-3.5 w-3.5" /> Right 90°</Button>
            </div>
            <FineRotationControl value={props.fineRotation} disabled={busy} onChange={props.onFineRotation} onInteractionChange={props.onRotationInteraction} />
          </section>
          <section className="border-t border-slate-100 pt-4">
            <SharpnessControl value={props.sharpness} disabled={busy} onChange={props.onSharpness} />
          </section>
        </div>
      </aside>
    </div>
  );
}

function FineRotationControl({ value, disabled, onChange, onInteractionChange }: {
  value: number; disabled: boolean; onChange: (value: number) => void; onInteractionChange: (value: boolean) => void;
}) {
  const [draftDegrees, setDraftDegrees] = useState<string | null>(null);
  return <div>
    <div className="flex items-center justify-between gap-2">
      <label htmlFor="passport-image-fine-rotation" className="text-xs font-medium text-slate-600">Fine rotation</label>
      <div className="flex items-center gap-2">
        <button type="button" aria-label="Reset fine rotation" disabled={disabled || value === 0} onClick={() => onChange(0)} className="text-[11px] text-slate-500 hover:text-blue-700 disabled:opacity-35">Reset</button>
        <div className="flex items-center rounded-lg border border-slate-200 bg-slate-50 pr-2">
          <input type="number" aria-label="Fine rotation degrees" min={MIN_FINE_ROTATION} max={MAX_FINE_ROTATION} step="1" value={draftDegrees ?? String(value)} disabled={disabled}
            onFocus={() => setDraftDegrees(String(value))}
            onChange={event => {
              const text = event.target.value;
              setDraftDegrees(text);
              if (text !== "" && Number.isFinite(Number(text))) onChange(Number(text));
            }}
            onBlur={() => setDraftDegrees(null)}
            className="h-8 w-14 rounded-lg bg-transparent pl-2 text-right text-xs font-semibold tabular-nums text-slate-800 outline-none focus:ring-2 focus:ring-blue-500" /><span className="text-xs text-slate-500">°</span>
        </div>
      </div>
    </div>
    <input id="passport-image-fine-rotation" type="range" min={MIN_FINE_ROTATION} max={MAX_FINE_ROTATION} step="1" value={value} disabled={disabled}
      onPointerDown={() => onInteractionChange(true)} onPointerUp={() => onInteractionChange(false)} onPointerCancel={() => onInteractionChange(false)}
      onLostPointerCapture={() => onInteractionChange(false)} onBlur={() => onInteractionChange(false)} onChange={event => onChange(Number(event.target.value))}
      className="mt-3 h-5 w-full touch-none accent-blue-600" />
    <div className="flex justify-between text-[10px] tabular-nums text-slate-400"><span>−45°</span><span>0°</span><span>+45°</span></div>
  </div>;
}

function SharpnessControl({ value, disabled, onChange }: { value: number; disabled: boolean; onChange: (value: number) => void }) {
  return <div>
    <div className="flex items-center justify-between gap-3">
      <label htmlFor="passport-image-sharpness" className="flex items-center gap-2 text-sm font-semibold text-slate-800"><SlidersHorizontal className="h-4 w-4 text-blue-600" /> Sharpness</label>
      <output htmlFor="passport-image-sharpness" className="rounded-md bg-blue-50 px-2 py-1 text-xs font-semibold tabular-nums text-blue-700">{Math.round(value * 100)}%</output>
    </div>
    <p className="mt-2 text-xs leading-5 text-slate-500">Bring out text and fine detail.</p>
    <input id="passport-image-sharpness" type="range" min="1" max="3" step="0.05" value={value} disabled={disabled}
      onChange={event => onChange(Number(event.target.value))} className="mt-2 h-5 w-full accent-blue-600" />
    <div className="mt-1 grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1">
      {([[1, "Natural"], [1.75, "Clear"], [2.5, "Crisp"]] as const).map(([level, name]) => <button key={name} type="button" disabled={disabled} aria-pressed={Math.abs(value - level) < 0.01}
        onClick={() => onChange(level)} className={`rounded-md py-1.5 text-[11px] font-medium disabled:opacity-40 ${Math.abs(value - level) < 0.01 ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>{name}</button>)}
    </div>
  </div>;
}

function CropShade({ crop }: { crop: PassportImageCropRect }) {
  const right = crop.x + crop.width;
  const bottom = crop.y + crop.height;
  const shared = "pointer-events-none absolute bg-slate-950/60";
  return <>
    <div className={shared} style={{ inset: `0 0 ${percent(1 - crop.y)} 0` }} />
    <div className={shared} style={{ inset: `${percent(bottom)} 0 0 0` }} />
    <div className={shared} style={{ inset: `${percent(crop.y)} ${percent(1 - crop.x)} ${percent(1 - bottom)} 0` }} />
    <div className={shared} style={{ inset: `${percent(crop.y)} 0 ${percent(1 - bottom)} ${percent(right)}` }} />
  </>;
}
function percent(value: number) { return `${value * 100}%`; }
function cornerLabel(corner: Exclude<CropDragMode, "move">) { return ({ nw: "top left", ne: "top right", sw: "bottom left", se: "bottom right" })[corner]; }
function cornerClassName(corner: Exclude<CropDragMode, "move">) { return `${corner.startsWith("n") ? "-top-3.5" : "-bottom-3.5"} ${corner.endsWith("w") ? "-left-3.5" : "-right-3.5"}`; }
