"use client";

import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { DocumentDeliveryActivity } from "@/features/documents/components/document-delivery-activity";
import { cn } from "@/lib/utils/cn";
import { type DisplayedWhatsAppActivity, WHATSAPP_ACTIVITY_POSITION_KEY } from "../../utils/activity-tracking";
import type { WhatsAppActivityTrackerValue } from "./context";
import { WhatsAppActivityRow } from "./row";

const FLOATING_EDGE_GAP = 16;

const DRAG_INTENT_THRESHOLD_PX = 4;

const DRAG_EXCLUSION_SELECTOR =
  "button, input, textarea, select, [role='button'], [data-whatsapp-activity-no-drag]";

interface Position {
  x: number;
  y: number;
}

interface DragState {
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  width: number;
  height: number;
  latestX: number;
  latestY: number;
  moved: boolean;
}

function readFloatingPosition(): Position | null {
  try {
    const raw = window.localStorage.getItem(WHATSAPP_ACTIVITY_POSITION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Position>;
    return typeof parsed.x === "number"
      && Number.isFinite(parsed.x)
      && typeof parsed.y === "number"
      && Number.isFinite(parsed.y)
      ? { x: parsed.x, y: parsed.y }
      : null;
  } catch {
    return null;
  }
}

function clampPosition(
  x: number,
  y: number,
  width: number,
  height: number,
): Position {
  return {
    x: Math.min(
      Math.max(FLOATING_EDGE_GAP, x),
      Math.max(FLOATING_EDGE_GAP, window.innerWidth - width - FLOATING_EDGE_GAP),
    ),
    y: Math.min(
      Math.max(FLOATING_EDGE_GAP, y),
      Math.max(FLOATING_EDGE_GAP, window.innerHeight - height - FLOATING_EDGE_GAP),
    ),
  };
}

export function DraggableWhatsAppActivityOverlay({
  activities,
  onDismiss,
}: {
  activities: DisplayedWhatsAppActivity[];
  onDismiss: WhatsAppActivityTrackerValue["dismissActivity"];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const suppressClickAfterDragRef = useRef(false);
  const [position, setPosition] = useState<Position | null>(readFloatingPosition);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const keepInsideViewport = () => {
      setPosition((current) => {
        if (!current) return current;
        const next = clampPosition(
          current.x,
          current.y,
          container.offsetWidth,
          container.offsetHeight,
        );
        return next.x === current.x && next.y === current.y ? current : next;
      });
    };
    const observer = new ResizeObserver(keepInsideViewport);
    observer.observe(container);
    window.addEventListener("resize", keepInsideViewport);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", keepInsideViewport);
    };
  }, []);

  useEffect(() => {
    if (!position) return;
    try {
      window.localStorage.setItem(
        WHATSAPP_ACTIVITY_POSITION_KEY,
        JSON.stringify(position),
      );
    } catch {
      // Position persistence is optional; dragging still works in memory.
    }
  }, [position]);

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target;
    if (
      event.button !== 0
      || !(target instanceof Element)
      || target.closest(DRAG_EXCLUSION_SELECTOR)
    ) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: rect.left,
      originY: rect.top,
      width: rect.width,
      height: rect.height,
      latestX: rect.left,
      latestY: rect.top,
      moved: false,
    };
  };

  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - drag.startX;
    const deltaY = event.clientY - drag.startY;
    if (
      !drag.moved
      && Math.hypot(deltaX, deltaY) < DRAG_INTENT_THRESHOLD_PX
    ) {
      return;
    }
    if (!drag.moved) {
      drag.moved = true;
      setDragging(true);
    }
    event.preventDefault();
    const next = clampPosition(
      drag.originX + deltaX,
      drag.originY + deltaY,
      drag.width,
      drag.height,
    );
    drag.latestX = next.x;
    drag.latestY = next.y;
    const container = containerRef.current;
    if (container) {
      container.style.transform = `translate3d(${next.x - drag.originX}px, ${
        next.y - drag.originY
      }px, 0)`;
    }
  };

  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.currentTarget.style.transform = "";
    if (drag.moved) {
      setPosition({ x: drag.latestX, y: drag.latestY });
      suppressClickAfterDragRef.current = true;
      window.setTimeout(() => {
        suppressClickAfterDragRef.current = false;
      }, 0);
    }
    dragStateRef.current = null;
    setDragging(false);
  };

  const suppressClickAfterDrag = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (!suppressClickAfterDragRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    suppressClickAfterDragRef.current = false;
  };

  return (
    <div
      ref={containerRef}
      className={cn(
        "fixed z-[95] max-h-[calc(100vh-32px)] w-[min(420px,calc(100vw-32px))] cursor-grab select-none space-y-2 overflow-y-auto overscroll-contain active:cursor-grabbing",
        dragging && "cursor-grabbing will-change-transform",
      )}
      style={
        position
          ? { left: position.x, top: position.y }
          : { bottom: FLOATING_EDGE_GAP, right: FLOATING_EDGE_GAP }
      }
      data-whatsapp-activity-floating
      onPointerDown={startDrag}
      onPointerMove={moveDrag}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
      onClickCapture={suppressClickAfterDrag}
      aria-label="Movable WhatsApp delivery progress"
    >
      {activities.map((activity) => activity.kind === "document" ? (
        <DocumentDeliveryActivity
          key={`${activity.kind}:${activity.activity_id}`}
          activity={activity}
          variant="floating"
          onDismiss={onDismiss}
        />
      ) : (
        <WhatsAppActivityRow
          key={`${activity.kind}:${activity.activity_id}`}
          activity={activity}
          variant="floating"
          onDismiss={onDismiss}
        />
      ))}
    </div>
  );
}
