"use client";

import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal-keyboard-boundary";
import { Bell } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import { useNotificationCenter } from "../hooks/use-notification-center";
import { NotificationPanel } from "./notification-panel";

export function NotificationBell() {
  const center = useNotificationCenter();
  const { isOpen, setIsOpen, unreadCount } = center;
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const closePanel = useCallback(() => setIsOpen(false), [setIsOpen]);
  const returnFocusTarget = useCallback(() => triggerRef.current, []);
  const onKeyDown = useModalKeyboardBoundary({
    dialogRef: panelRef, isOpen, canClose: true, onClose: closePanel, returnFocusTarget,
  });

  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      // A nested modal owns its own outside-click boundary.
      if (panelRef.current?.closest("[inert]")) return;
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) closePanel();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isOpen, closePanel]);

  return (
    <div ref={containerRef} className="relative">
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="icon"
        className="relative h-10 w-10 text-slate-500 hover:text-slate-900"
        aria-label={`Notifications, ${unreadCount} unread`}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls="dashboard-notification-panel"
        onClick={() => setIsOpen((current) => !current)}
      >
        <Bell className="h-5 w-5" aria-hidden="true" />
        {unreadCount > 0 && (
          <span
            className="absolute right-0.5 top-0.5 flex min-h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-4 text-white ring-2 ring-white"
            aria-hidden="true"
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {unreadCount === 1
          ? "1 unread notification"
          : `${unreadCount} unread notifications`}
      </span>

      {isOpen && <NotificationPanel center={center} panelRef={panelRef} onKeyDown={onKeyDown} closePanel={closePanel} />}
    </div>
  );
}
