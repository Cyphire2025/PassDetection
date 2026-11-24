"use client";

import { useEffect, useId, useRef, useState } from "react";

export function usePassportGroupMenus() {
  const actionsMenuRef = useRef<HTMLDivElement | null>(null);
  const actionsMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const actionsMenuPopupRef = useRef<HTMLDivElement | null>(null);
  const bulkActionsMenuRef = useRef<HTMLDivElement | null>(null);
  const bulkActionsButtonRef = useRef<HTMLButtonElement | null>(null);
  const bulkActionsDisclosureId = useId();
  const [isActionsMenuOpen, setIsActionsMenuOpen] = useState(false);
  const [actionsMenuPosition, setActionsMenuPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);
  const [isBulkActionsMenuOpen, setIsBulkActionsMenuOpen] = useState(false);
  useEffect(() => {
    if (!isActionsMenuOpen)
      return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!actionsMenuRef.current?.contains(target) &&
        !actionsMenuPopupRef.current?.contains(target)) {
        setIsActionsMenuOpen(false);
        setActionsMenuPosition(null);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsActionsMenuOpen(false);
        setActionsMenuPosition(null);
        actionsMenuButtonRef.current?.focus();
      }
    };
    const closeOnViewportChange = () => {
      setIsActionsMenuOpen(false);
      setActionsMenuPosition(null);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnViewportChange);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnViewportChange);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [isActionsMenuOpen]);
  useEffect(() => {
    if (!isBulkActionsMenuOpen)
      return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!bulkActionsMenuRef.current?.contains(event.target as Node) &&
        !bulkActionsButtonRef.current?.contains(event.target as Node)) {
        setIsBulkActionsMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsBulkActionsMenuOpen(false);
        bulkActionsButtonRef.current?.focus();
      }
    };
    const closeOnViewportChange = (event: Event) => {
      if (event.target instanceof Node && bulkActionsMenuRef.current?.contains(event.target)) return;
      setIsBulkActionsMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnViewportChange);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnViewportChange);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [isBulkActionsMenuOpen]);
  return {
    actionsMenuRef,
    actionsMenuButtonRef,
    actionsMenuPopupRef,
    bulkActionsMenuRef,
    bulkActionsButtonRef,
    bulkActionsDisclosureId,
    isActionsMenuOpen,
    setIsActionsMenuOpen,
    actionsMenuPosition,
    setActionsMenuPosition,
    isBulkActionsMenuOpen,
    setIsBulkActionsMenuOpen,
  };
}
