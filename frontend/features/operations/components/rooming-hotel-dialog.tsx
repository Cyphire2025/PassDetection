"use client";

import { type FormEvent, type ReactNode, useId, useRef, useState } from "react";
import { Hotel, X } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { RoomingHotel } from "../api/operations.api";
import { roomingErrorMessage } from "./rooming-error-message";

interface HotelStayValues {
  hotel_name: string;
  city?: string;
  check_in_date?: string;
  check_out_date?: string;
}

interface HotelDialogProps {
  isLoading: boolean;
  onClose: () => void;
}

export function CreateHotelDialog({ onCreate, ...props }: HotelDialogProps & {
  onCreate: (body: HotelStayValues) => Promise<void>;
}) {
  return <HotelStayDialog {...props} onSave={onCreate} />;
}

export function EditHotelDialog({ hotel, onSave, ...props }: HotelDialogProps & {
  hotel: RoomingHotel;
  onSave: (body: HotelStayValues) => Promise<void>;
}) {
  return <HotelStayDialog {...props} hotel={hotel} onSave={onSave} />;
}

function HotelStayDialog({ hotel, isLoading, onClose, onSave }: HotelDialogProps & {
  hotel?: RoomingHotel;
  onSave: (body: HotelStayValues) => Promise<void>;
}) {
  const [form, setForm] = useState({
    hotel_name: hotel?.hotel_name ?? "",
    city: hotel?.city ?? "",
    check_in_date: hotel?.check_in_date ?? "",
    check_out_date: hotel?.check_out_date ?? "",
  });
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      await onSave({
        hotel_name: form.hotel_name.trim(),
        city: form.city.trim() || undefined,
        check_in_date: form.check_in_date || undefined,
        check_out_date: form.check_out_date || undefined,
      });
    } catch (saveError) {
      setError(roomingErrorMessage(saveError, hotel
        ? "Hotel details could not be saved. Check the stay dates and try again."
        : "Hotel could not be added. Check the stay dates and try again."));
    }
  };

  return (
    <DialogShell
      title={hotel ? `Edit ${hotel.hotel_name}` : "Add hotel stay"}
      icon={<Hotel className="h-5 w-5" aria-hidden="true" />}
      isLoading={isLoading}
      onClose={onClose}
    >
      <form className="space-y-4" onSubmit={submit}>
        <Input
          label="Hotel name"
          placeholder={hotel ? undefined : "Marriott Bangkok"}
          value={form.hotel_name}
          onChange={(event) => setForm((current) => ({ ...current, hotel_name: event.target.value }))}
          minLength={2}
          maxLength={255}
          required
          autoFocus
        />
        <Input
          label="City"
          placeholder={hotel ? undefined : "Bangkok"}
          value={form.city}
          onChange={(event) => setForm((current) => ({ ...current, city: event.target.value }))}
          maxLength={120}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            label="Check-in"
            type="date"
            value={form.check_in_date}
            onChange={(event) => setForm((current) => ({ ...current, check_in_date: event.target.value }))}
          />
          <Input
            label="Check-out"
            type="date"
            min={form.check_in_date || undefined}
            value={form.check_out_date}
            onChange={(event) => setForm((current) => ({ ...current, check_out_date: event.target.value }))}
          />
        </div>
        {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        <DialogActions onClose={onClose} isLoading={isLoading} label={hotel ? "Save hotel" : "Add hotel"} />
      </form>
    </DialogShell>
  );
}

function DialogShell({ title, icon, isLoading, onClose, children }: HotelDialogProps & {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !isLoading, onClose });

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
      onMouseDown={(event) => { if (event.target === event.currentTarget && !isLoading) onClose(); }}
    >
      <div
        ref={dialogRef}
        onKeyDown={handleKeyDown}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">{icon}</span>
            <h2 id={titleId} className="font-semibold text-slate-900">{title}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label="Close hotel dialog"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function DialogActions({ onClose, isLoading, label }: HotelDialogProps & { label: string }) {
  return (
    <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
      <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button>
      <Button type="submit" isLoading={isLoading}>{label}</Button>
    </div>
  );
}
