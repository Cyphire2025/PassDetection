"use client";

import Image from "next/image";
import { ChevronLeft, ChevronRight, Download, X } from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";
import type { Asset, VisualState } from "../types";
import styles from "./image-reveal.module.css";

export function ImageReveal({ asset, images, presentationRef, onSelect, onClosed, onProgress }: {
  asset: Asset | null; images: Asset[]; presentationRef: RefObject<VisualState>;
  onSelect: (image: Asset) => void; onClosed: () => void;
  onProgress: () => void;
}) {
  const [rendered, setRendered] = useState<Asset | null>(asset);
  const [closing, setClosing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [requested, setRequested] = useState(asset);
  const root = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const progress = useRef(0);
  const closingCallback = useRef(onClosed);
  useEffect(() => { closingCallback.current = onClosed; }, [onClosed]);
  // Adjust selection during rendering so a new image never paints with the previous
  // image's load state. Closing keeps the current asset until the return animation ends.
  if (asset !== requested) {
    setRequested(asset);
    if (asset) { setRendered(asset); setClosing(false); setLoaded(false); setFailed(false); }
    else if (rendered) setClosing(true);
  }
  useEffect(() => {
    if (asset && progress.current === 0) previousFocus.current = document.activeElement as HTMLElement;
  }, [asset]);
  useEffect(() => {
    const element = root.current;
    if (!element || !rendered) return;
    const updateSize = () => { const panel = element.querySelector<HTMLElement>("[data-image-panel]");
      if (panel) { presentationRef.current.revealWidth = panel.offsetWidth; presentationRef.current.revealHeight = panel.offsetHeight; onProgress(); } };
    updateSize(); const observer = new ResizeObserver(updateSize); observer.observe(element);
    return () => observer.disconnect();
  }, [rendered, presentationRef, onProgress]);
  useEffect(() => {
    if (!rendered || (!loaded && !closing)) return;
    const element = root.current;
    if (!element) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = progress.current; const target = closing ? 0 : 1; const started = performance.now();
    let frame = 0;
    const animate = (now: number) => {
      const time = reduced ? 1 : Math.min(1, (now - started) / (closing ? 950 : 1300));
      const eased = time < .5 ? 4 * time ** 3 : 1 - (-2 * time + 2) ** 3 / 2;
      const value = from + (target - from) * eased;
      progress.current = value; presentationRef.current.reveal = value;
      onProgress();
      element.style.setProperty("--reveal", String(value));
      if (time < 1) frame = requestAnimationFrame(animate);
      else if (closing) { setRendered(null); closingCallback.current(); previousFocus.current?.focus(); }
      else closeButton.current?.focus({ preventScroll: true });
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [rendered, loaded, closing, presentationRef, onProgress]);
  useEffect(() => () => { presentationRef.current.reveal = 0; }, [presentationRef]);
  useEffect(() => {
    if (!rendered) return;
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") setClosing(true); };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [rendered]);
  if (!rendered) return null;
  const index = images.findIndex((image) => image.id === rendered.id);
  const next = (direction: number) => onSelect(images[(index + direction + images.length) % images.length]);
  return <div className={styles.reveal} ref={root} data-testid="image-reveal" data-closing={closing}>
    <div className={styles.panel} data-image-panel role="region" aria-label={`Image viewer: ${rendered.name}`}>
      <Image key={rendered.id} src={rendered.url} alt={rendered.name} fill unoptimized sizes="(max-width: 639px) 80vw, 640px" onLoad={() => setLoaded(true)} onError={() => { setFailed(true); setLoaded(true); }} />
      {failed ? <p className={styles.loadError} role="alert">This image could not be opened. Close it and try again from your library.</p> : null}
      <div className={styles.imageShade} />
      <a className={styles.download} href={rendered.url} download={rendered.name} aria-label="Download image"><Download size={16} /></a>
      <button type="button" ref={closeButton} onClick={() => setClosing(true)} className={styles.close} aria-label="Close image"><X size={17} /></button>
      <div className={styles.caption}><span>{rendered.kind === "generated" ? "Created for you" : "From your library"}</span><p>{rendered.name}</p></div>
      {images.length > 1 ? <div className={styles.paging}><button type="button" onClick={() => next(-1)} aria-label="Previous image"><ChevronLeft size={16} /></button><span>{index + 1} / {images.length}</span><button type="button" onClick={() => next(1)} aria-label="Next image"><ChevronRight size={16} /></button></div> : null}
    </div>
    {images.length > 1 ? <div className={styles.filmstrip} aria-label="Image selection">{images.map((image) => <button key={image.id} type="button" aria-label={`Select ${image.name}`} aria-pressed={image.id === rendered.id} onClick={() => onSelect(image)}><Image src={image.url} alt="" fill unoptimized sizes="64px" /></button>)}</div> : null}
  </div>;
}
