"use client";

import { Check, MoreHorizontal, Pencil, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui";
import { useUpdateWhatsAppRecipientPhone } from "../hooks/use-whatsapp";
import { readErrorMessage } from "../components/whatsapp-dialog-ui";
import { fieldClass } from "./workspace-ui";

export function RecipientPhoneCell({
  groupId,
  recipientId,
  number,
  editing,
  disabled,
  onEdit,
  onDone,
}: {
  groupId: string;
  recipientId: string;
  number: string;
  editing: boolean;
  disabled?: boolean;
  onEdit: () => void;
  onDone: () => void;
}) {
  const mutation = useUpdateWhatsAppRecipientPhone();
  const queryClient = useQueryClient();
  if (!editing)
    return (
      <div className="flex items-center gap-2">
        <span className="whitespace-nowrap tabular-nums text-slate-600">
          {number}
        </span>
        {!disabled && (
          <button
            type="button"
            onClick={() => {
              mutation.reset();
              onEdit();
            }}
            aria-label={`Edit WhatsApp number ${number}`}
            className="rounded-md p-1.5 text-slate-400 hover:bg-blue-50 hover:text-blue-700"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    );
  return (
    <div className="min-w-60">
      <form
        className="flex items-center gap-1.5"
        onSubmit={async (event) => {
          event.preventDefault();
          if (mutation.isPending) return;
          const phoneNumber = String(
            new FormData(event.currentTarget).get("phone") ?? "",
          ).trim();
          try {
            await mutation.mutateAsync({ groupId, recipientId, phoneNumber });
            void queryClient.invalidateQueries({
              queryKey: ["whatsapp", "history", groupId],
            });
            onDone();
          } catch {
            /* mutation error is rendered inline */
          }
        }}
      >
        <input
          autoFocus
          name="phone"
          type="tel"
          aria-label="New WhatsApp number"
          defaultValue={number}
          required
          maxLength={64}
          disabled={mutation.isPending}
          className={fieldClass}
        />
        <Button
          type="submit"
          size="icon"
          variant="ghost"
          aria-label="Save WhatsApp number"
          isLoading={mutation.isPending}
        >
          <Check className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="Cancel number edit"
          disabled={mutation.isPending}
          onClick={onDone}
        >
          <X className="h-4 w-4" />
        </Button>
      </form>
      {mutation.error && (
        <p role="alert" className="mt-1.5 max-w-xs text-xs text-red-600">
          {readErrorMessage(mutation.error, "Could not update the number.")}
        </p>
      )}
    </div>
  );
}

export function RecipientRowMenu({
  name,
  children,
}: {
  name: string;
  children: (close: () => void) => ReactNode;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const anchor = useRef<DOMRect | null>(null);
  const [position, setPosition] = useState<{
    top: number;
    right: number;
  } | null>(null);
  const close = () => {
    setPosition(null);
  };
  useEffect(() => {
    if (!position) return;
    menu.current
      ?.querySelector<HTMLButtonElement>("button:not(:disabled)")
      ?.focus({ preventScroll: true });
    const outside = (event: PointerEvent) => {
      if (
        !menu.current?.contains(event.target as Node) &&
        !trigger.current?.contains(event.target as Node)
      )
        setPosition(null);
    };
    const dismiss = () => setPosition(null);
    const dismissAfterAnchorMoves = () => {
      const current = trigger.current?.getBoundingClientRect();
      const opened = anchor.current;
      // A click can arrive before the scroll event that brought its trigger
      // into view. That queued event must not dismiss a correctly placed menu.
      if (!current || !opened || current.top !== opened.top ||
        current.right !== opened.right || current.bottom !== opened.bottom ||
        current.left !== opened.left) dismiss();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("scroll", dismissAfterAnchorMoves, true);
    window.addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("scroll", dismissAfterAnchorMoves, true);
      window.removeEventListener("resize", dismiss);
    };
  }, [position]);
  return (
    <>
      <Button
        ref={trigger}
        type="button"
        size="icon"
        variant="ghost"
        aria-label={`Actions for ${name}`}
        aria-haspopup="menu"
        aria-expanded={Boolean(position)}
        aria-controls={position ? id : undefined}
        onClick={() => {
          if (position) {
            close();
            return;
          }
          const rect = trigger.current!.getBoundingClientRect();
          anchor.current = rect;
          setPosition({
            top: Math.max(
              8,
              Math.min(rect.bottom + 6, window.innerHeight - 190),
            ),
            right: Math.max(12, window.innerWidth - rect.right),
          });
        }}
      >
        <MoreHorizontal className="h-4 w-4" />
      </Button>
      {position &&
        createPortal(
          <div
            id={id}
            ref={menu}
            role="menu"
            aria-label={`Actions for ${name}`}
            style={position}
            className="fixed z-[70] min-w-48 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg [&_button]:flex [&_button]:w-full [&_button]:items-center [&_button]:gap-2 [&_button]:rounded-md [&_button]:px-3 [&_button]:py-2.5 [&_button]:text-left [&_button]:text-xs [&_button]:hover:bg-slate-50 [&_button]:focus-visible:outline-blue-500"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                trigger.current?.focus();
                event.preventDefault();
                event.stopPropagation();
                close();
              }
              if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                const buttons = [
                  ...event.currentTarget.querySelectorAll<HTMLButtonElement>(
                    "button:not(:disabled)",
                  ),
                ];
                const index = buttons.indexOf(
                  document.activeElement as HTMLButtonElement,
                );
                const next =
                  event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? buttons.length - 1
                      : (index +
                          (event.key === "ArrowDown" ? 1 : -1) +
                          buttons.length) %
                        buttons.length;
                buttons[next]?.focus();
              }
              if (event.key === "Tab") setPosition(null);
            }}
          >
            {children(close)}
          </div>,
          document.body,
        )}
    </>
  );
}
