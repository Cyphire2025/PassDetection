"use client";

import { Eye, Plus, Save, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import type { ItineraryDayDraft, ItineraryItemDraft, StructuredItinerary } from "../types";
import { createClientId, formatGcDateTime, gcAppErrorMessage } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";

export function ItineraryEditor({
  itinerary,
  isSaving,
  isPublishing,
  isUnpublishing,
  onSave,
  onPublish,
  onUnpublish,
}: {
  itinerary: StructuredItinerary;
  isSaving: boolean;
  isPublishing: boolean;
  isUnpublishing: boolean;
  onSave: (itinerary: StructuredItinerary) => Promise<void>;
  onPublish: (versionId: string) => Promise<void>;
  onUnpublish: (versionId: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(itinerary);
  const [preview, setPreview] = useState(false);
  const [publicationAction, setPublicationAction] = useState<"publish" | "unpublish" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    if (!draft.title.trim()) {
      setError("Enter an itinerary title before saving.");
      return;
    }
    if (draft.days.some((day) => !day.title.trim() || day.items.some((item) => !item.title.trim()))) {
      setError("Every itinerary day and item needs a title.");
      return;
    }
    try {
      await onSave({
        ...draft,
        days: draft.days.map((day, dayIndex) => ({
          ...day,
          day_number: dayIndex + 1,
          items: day.items,
        })),
      });
    } catch (saveError) {
      setError(gcAppErrorMessage(saveError, "The itinerary draft could not be saved."));
    }
  };

  const addDay = () => setDraft((current) => ({
    ...current,
    days: [...current.days, {
      client_id: createClientId("day"),
      day_number: current.days.length + 1,
      date: "",
      title: `Day ${current.days.length + 1}`,
      items: [],
    }],
  }));

  const updateDay = (dayId: string, patch: Partial<ItineraryDayDraft>) => setDraft((current) => ({
    ...current,
    days: current.days.map((day) => day.client_id === dayId ? { ...day, ...patch } : day),
  }));

  const addItem = (dayId: string) => setDraft((current) => ({
    ...current,
    days: current.days.map((day) => day.client_id === dayId ? {
      ...day,
      items: [...day.items, emptyItem()],
    } : day),
  }));

  const updateItem = (dayId: string, itemId: string, patch: Partial<ItineraryItemDraft>) => setDraft((current) => ({
    ...current,
    days: current.days.map((day) => day.client_id === dayId ? {
      ...day,
      items: day.items.map((item) => item.client_id === itemId ? { ...item, ...patch } : item),
    } : day),
  }));

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold text-slate-900">Structured itinerary</h3>
                <Badge variant={itinerary.status === "published" ? "success" : "outline"}>
                  {itinerary.status === "published" ? `Published v${itinerary.published_version}` : itinerary.status === "draft" ? "Saved draft" : "Draft only"}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-slate-500">Draft edits remain hidden until explicitly published.</p>
              {itinerary.published_at && <p className="mt-1 text-xs text-slate-500">Last published {formatGcDateTime(itinerary.published_at)}</p>}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" size="sm" leftIcon={<Eye className="h-4 w-4" />} onClick={() => setPreview((value) => !value)}>
                {preview ? "Edit draft" : "Preview"}
              </Button>
              <Button type="button" variant="secondary" size="sm" leftIcon={<Save className="h-4 w-4" />} isLoading={isSaving} disabled={isPublishing} onClick={() => void save()}>
                Save draft
              </Button>
              {itinerary.status === "published" ? (
                <Button type="button" variant="secondary" size="sm" disabled={isSaving} onClick={() => setPublicationAction("unpublish")}>Unpublish itinerary</Button>
              ) : (
                <Button type="button" size="sm" leftIcon={<Send className="h-4 w-4" />} disabled={isSaving || draft.days.length === 0 || !itinerary.version_id || itinerary.status !== "draft"} onClick={() => setPublicationAction("publish")}>
                  Publish saved draft
                </Button>
              )}
            </div>
          </div>
          {error && <GcAlert message={error} />}
          <Input label="Itinerary title" value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} disabled={preview} />
        </CardContent>
      </Card>

      {preview ? (
        <ItineraryPreview itinerary={draft} />
      ) : (
        <div className="space-y-4">
          {draft.days.map((day, dayIndex) => (
            <Card key={day.client_id}>
              <CardContent className="space-y-4 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="grid flex-1 gap-3 md:grid-cols-[110px_minmax(0,1fr)_180px]">
                    <Input label="Day" value={String(dayIndex + 1)} disabled />
                    <Input label="Day title" value={day.title} onChange={(event) => updateDay(day.client_id, { title: event.target.value })} />
                    <Input label="Date" type="date" value={day.date} onChange={(event) => updateDay(day.client_id, { date: event.target.value })} />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="mt-6 text-red-600 hover:bg-red-50 hover:text-red-700"
                    aria-label={`Remove day ${dayIndex + 1}`}
                    onClick={() => setDraft((current) => ({ ...current, days: current.days.filter((item) => item.client_id !== day.client_id) }))}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>

                <div className="space-y-3 border-l-2 border-blue-100 pl-4">
                  {day.items.length === 0 && <p className="text-sm text-slate-500">No itinerary items for this day.</p>}
                  {day.items.map((item) => (
                    <div key={item.client_id} className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <div className="grid gap-3 md:grid-cols-[110px_minmax(0,1fr)_minmax(0,1fr)_auto]">
                        <Input label="Time" type="time" value={item.time} onChange={(event) => updateItem(day.client_id, item.client_id, { time: event.target.value })} />
                        <Input label="Item title" value={item.title} onChange={(event) => updateItem(day.client_id, item.client_id, { title: event.target.value })} />
                        <Input label="Location" value={item.location} onChange={(event) => updateItem(day.client_id, item.client_id, { location: event.target.value })} />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="mt-6 text-red-600 hover:bg-red-50"
                          aria-label={`Remove ${item.title || "itinerary item"}`}
                          onClick={() => updateDay(day.client_id, { items: day.items.filter((candidate) => candidate.client_id !== item.client_id) })}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2">
                        <label className="flex flex-col gap-1.5 text-sm font-medium text-slate-700">
                          Description
                          <textarea
                            value={item.description}
                            onChange={(event) => updateItem(day.client_id, item.client_id, { description: event.target.value })}
                            rows={2}
                            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-blue-600"
                          />
                        </label>
                        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs leading-5 text-slate-500">Map coordinates and deep links can be added when location geocoding is enabled. The saved location name remains available offline.</div>
                      </div>
                    </div>
                  ))}
                  <Button type="button" variant="secondary" size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={() => addItem(day.client_id)}>
                    Add itinerary item
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
          <Button type="button" variant="secondary" leftIcon={<Plus className="h-4 w-4" />} onClick={addDay}>Add itinerary day</Button>
        </div>
      )}

      <GcDialog
        open={publicationAction !== null}
        title={publicationAction === "unpublish" ? "Unpublish itinerary" : "Publish itinerary"}
        description={publicationAction === "unpublish" ? "The current itinerary will stop being available to mobile users." : "The current saved draft will become visible to eligible mobile users and increment the itinerary version."}
        onClose={() => !(isPublishing || isUnpublishing) && setPublicationAction(null)}
        closeDisabled={isPublishing || isUnpublishing}
        size="md"
        footer={(
          <>
            <Button type="button" variant="secondary" onClick={() => setPublicationAction(null)} disabled={isPublishing || isUnpublishing}>Cancel</Button>
            <Button
              type="button"
              variant={publicationAction === "unpublish" ? "danger" : "primary"}
              isLoading={isPublishing || isUnpublishing}
              onClick={() => {
                setError(null);
                if (!itinerary.version_id || !publicationAction) return;
                const request = publicationAction === "unpublish" ? onUnpublish(itinerary.version_id) : onPublish(itinerary.version_id);
                void request.then(() => setPublicationAction(null)).catch((publishError: unknown) => {
                  setError(gcAppErrorMessage(publishError, `The itinerary could not be ${publicationAction === "unpublish" ? "unpublished" : "published"}.`));
                  setPublicationAction(null);
                });
              }}
            >
              {publicationAction === "unpublish" ? "Unpublish now" : "Publish now"}
            </Button>
          </>
        )}
      >
        <p className="text-sm leading-6 text-slate-600">{publicationAction === "unpublish" ? "Eligible devices will receive a removal version on their next synchronization." : "Review the Preview before publishing. Mobile devices will receive compact version metadata and synchronize the changed itinerary."}</p>
      </GcDialog>
    </div>
  );
}

function ItineraryPreview({ itinerary }: { itinerary: StructuredItinerary }) {
  return (
    <Card>
      <CardContent className="space-y-5 p-5">
        <h3 className="text-lg font-semibold text-slate-900">{itinerary.title || "Untitled itinerary"}</h3>
        {itinerary.days.length === 0 ? <p className="text-sm text-slate-500">No days have been added.</p> : itinerary.days.map((day, index) => (
          <section key={day.client_id} className="border-l-2 border-blue-200 pl-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Day {index + 1}{day.date ? ` · ${day.date}` : ""}</p>
            <h4 className="mt-1 font-semibold text-slate-900">{day.title}</h4>
            <div className="mt-3 space-y-3">
              {day.items.map((item) => (
                <div key={item.client_id} className="rounded-xl bg-slate-50 p-3">
                  <p className="text-sm font-medium text-slate-900">{item.time && <span className="mr-2 text-blue-700">{item.time}</span>}{item.title}</p>
                  {item.location && <p className="mt-1 text-xs text-slate-500">{item.location}</p>}
                  {item.description && <p className="mt-2 text-sm text-slate-600">{item.description}</p>}
                </div>
              ))}
            </div>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}

function emptyItem(): ItineraryItemDraft {
  return {
    client_id: createClientId("item"),
    time: "",
    title: "",
    description: "",
    location: "",
  };
}
