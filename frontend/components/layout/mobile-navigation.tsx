"use client";

import { useRef } from "react";
import { X } from "lucide-react";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal-keyboard-boundary";

interface MobileNavigationProps {
  open: boolean;
  onClose: () => void;
}

const navigationTrigger = () => document.querySelector<HTMLElement>("[data-mobile-navigation-trigger]");

export function MobileNavigation({ open, onClose }: MobileNavigationProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: open, canClose: true, onClose, returnFocusTarget: navigationTrigger });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] lg:hidden" data-mobile-navigation-root>
      <div
        className="absolute inset-0 bg-slate-950/45 backdrop-blur-[1px]"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        ref={dialogRef}
        id="mobile-dashboard-navigation"
        role="dialog"
        aria-modal="true"
        aria-label="Dashboard navigation"
        className="relative h-full w-[min(20rem,88vw)] bg-white shadow-2xl"
        onKeyDown={handleKeyDown}
      >
        <Button
          data-dialog-initial-focus
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Close navigation"
          onClick={onClose}
          className="absolute right-3 top-2.5 z-10 text-slate-500 hover:text-slate-900"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </Button>
        <Sidebar mobile onNavigate={onClose} />
      </div>
    </div>
  );
}
