"use client";

import { ArrowRight, ImagePlus, RefreshCw, Send } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { ROUTES } from "@/constants/routes";
import { Button } from "@/components/ui";
import {
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { ComposerPreview, ComposerTextField } from "./composer-primitives";
import { useMessageComposer } from "./use-message-composer";
import { ComposerAudience } from "./message-composer-audience";
import type { MessageDefinition } from "./composer.api";
import { fieldClass } from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export type ComposerController = ReturnType<typeof useMessageComposer>;

export function BroadcastMessageComposer({
  definition,
}: {
  definition: MessageDefinition;
}) {
  const model = useMessageComposer(definition);
  const [checkedHistory, setCheckedHistory] = useState(false);
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">
          {definition.label}
        </h2>
        <p className="mt-1 text-sm text-slate-500">{definition.description}</p>
      </div>
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (model.ready || model.recovery) {
            setCheckedHistory(false);
            model.setReviewing(true);
          }
        }}
      >
        <section
          className={`${styles.surface} p-5 sm:p-6`}
          aria-label="Message editor and preview"
        >
          <div className="grid items-start gap-7 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <fieldset
              disabled={Boolean(model.group.is_archived) || model.pending}
              className="min-w-0 space-y-5"
            >
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <h3 className="text-sm font-semibold text-slate-900">
                  Write your message
                </h3>
                <span className="text-xs text-slate-400">Editable content</span>
              </div>
              {definition.fields.map((field) =>
                field.kind === "textarea" ? (
                  <ComposerTextField
                    key={field.key}
                    label={field.label}
                    value={model.fields[field.key] ?? ""}
                    required={field.required}
                    maxLength={field.max_length}
                    onChange={(value) =>
                      model.setState((current) => ({
                        ...current,
                        fields: { ...current.fields, [field.key]: value },
                      }))
                    }
                  />
                ) : (
                  <label
                    key={field.key}
                    className="block text-sm font-medium text-slate-700"
                  >
                    {field.label}
                    <input
                      type={field.kind}
                      required={field.required}
                      maxLength={field.max_length}
                      value={model.fields[field.key] ?? ""}
                      onChange={(event) =>
                        model.setState((current) => ({
                          ...current,
                          fields: {
                            ...current.fields,
                            [field.key]: event.target.value,
                          },
                        }))
                      }
                      className={`mt-2 ${fieldClass}`}
                    />
                  </label>
                ),
              )}
              {Object.entries(model.fieldErrors).map(([key, message]) => (
                <p key={key} role="alert" className="text-xs text-red-600">
                  {definition.fields.find((field) => field.key === key)?.label}:{" "}
                  {message}
                </p>
              ))}
              {definition.image_required && (
                <div>
                  <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-slate-300 px-4 py-3 transition hover:border-blue-400 hover:bg-blue-50/30 focus-within:ring-2 focus-within:ring-blue-500">
                    {model.imagePreview ? (
                      <Image
                        src={model.imagePreview}
                        alt="Selected message image"
                        width={48}
                        height={48}
                        unoptimized
                        className="h-12 w-12 rounded-md object-cover"
                      />
                    ) : (
                      <ImagePlus className="h-5 w-5 shrink-0 text-slate-400" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-medium text-slate-700">
                        Header image{" "}
                        <span className="text-slate-400">(required)</span>
                      </span>
                      <span className="mt-1 block truncate text-xs font-normal text-slate-500">
                        {model.image?.name ??
                          (model.imageId
                            ? "Saved image selected · choose a file to replace it"
                            : "JPEG or PNG · up to 5 MB")}
                      </span>
                    </span>
                    <span className="text-xs font-medium text-blue-700">
                      {model.image || model.imageId
                        ? "Replace"
                        : "Choose image"}
                    </span>
                    <input
                      type="file"
                      accept="image/jpeg,image/png"
                      className="sr-only"
                      aria-label="Header image"
                      onChange={(event) => {
                        const file = event.currentTarget.files?.[0];
                        event.currentTarget.value = "";
                        if (file) model.selectImage(file);
                      }}
                    />
                  </label>
                  {model.imageError && (
                    <p role="alert" className="mt-2 text-xs text-red-600">
                      {model.imageError}
                    </p>
                  )}
                </div>
              )}
              {definition.message_type === "passport_link" && (
                <label className="block text-sm font-medium text-slate-700">
                  Support contact
                  <select
                    value={model.state.supportContactId ?? ""}
                    onChange={(event) =>
                      model.setState((current) => ({
                        ...current,
                        supportContactId: event.target.value,
                      }))
                    }
                    className={`mt-2 ${fieldClass}`}
                    required
                  >
                    <option value="" disabled>
                      Choose a support contact
                    </option>
                    {model.group.support_contacts.map((contact) => (
                      <option key={contact.id} value={contact.id}>
                        {contact.name} · {contact.phone_number}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </fieldset>
            <aside
              className="min-w-0 lg:sticky lg:top-5"
              aria-label="Live WhatsApp preview"
            >
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">
                  WhatsApp preview
                </h3>
                <span role="status" className="text-xs text-slate-400">
                  {model.eligible.length === 0
                    ? "No available recipients"
                    : model.current
                      ? "Up to date"
                      : model.preview.error
                        ? "Preview unavailable"
                        : "Updating…"}
                </span>
              </div>
              <ComposerPreview
                message={model.preview.data?.rendered_message ?? null}
                recipientName={model.preview.data?.recipient_name}
                current={model.current}
                image={model.imagePreview}
                savedImage={Boolean(model.imageId)}
              >
                {model.audience.length > 1 && (
                  <label className="block text-xs font-medium text-slate-500">
                    Preview for
                    <select
                      aria-label="Preview recipient"
                      className={`mt-1.5 ${fieldClass}`}
                      value={
                        model.state.previewRecipientId ??
                        model.preview.data?.recipient_id ??
                        ""
                      }
                      onChange={(event) =>
                        model.setState((current) => ({
                          ...current,
                          previewRecipientId: event.target.value,
                        }))
                      }
                    >
                      {model.audience.map((recipient) => (
                        <option key={recipient.id} value={recipient.id}>
                          {recipient.name || recipient.normalized_phone_number}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </ComposerPreview>
            </aside>
          </div>
        </section>
        <ComposerAudience model={model} />
        {model.eligible.length === 0 && (
          <ErrorBanner message="No recipients are currently eligible for this message. Check Recipients and Delivery history; welcome delivery must be confirmed before follow-ups." />
        )}
        {model.preview.error && (
          <div className="space-y-2">
            <ErrorBanner
              message={readErrorMessage(
                model.preview.error,
                "The preview could not be checked.",
              )}
            />
            <Button
              type="button"
              variant="secondary"
              onClick={() => void model.preview.refetch()}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh preview
            </Button>
          </div>
        )}
        {model.current && !model.preview.data?.template_name && (
          <ErrorBanner message="Configure an approved template for this message in Settings before sending." />
        )}
        {model.current &&
          Boolean(model.preview.data?.welcome_required_count) && (
            <ErrorBanner
              message={
                model.preview.data?.welcome_required_reason ||
                "Some selected numbers need a delivered welcome message first."
              }
            />
          )}
        {!model.group.recipient_opt_in_confirmed && (
          <ErrorBanner message="Recipient opt-in has not been recorded for this broadcast. Confirm it before sending." />
        )}
        <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white/95 px-5 py-4 shadow-sm backdrop-blur-sm">
          <p aria-live="polite" className="text-xs text-slate-500">
            <strong className="font-semibold text-slate-900">
              {model.count === null
                ? "Checking audience…"
                : `${model.count.toLocaleString()} WhatsApp numbers ready`}
            </strong>
            {model.current &&
              (model.preview.data?.already_sent_count ?? 0) > 0 && (
                <span>
                  {" "}
                  · {model.preview.data?.already_sent_count} earlier recipients
                  excluded
                </span>
              )}
          </p>
          <Button type="submit" disabled={!model.ready && !model.recovery}>
            {model.recovery ? "Check earlier send" : "Review message"}
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </form>
      {model.reviewing && (
        <DialogFrame
          title="Review and send"
          description={`${definition.label} · ${model.group.name}`}
          onClose={() => model.setReviewing(false)}
          isBusy={model.pending}
        >
          <div className="space-y-5">
            <div className="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-3">
              <span className="text-sm text-slate-600">Selected audience</span>
              <strong className="text-sm text-slate-900">
                {model.reviewedCount} WhatsApp numbers
              </strong>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-xl bg-emerald-50 p-5 text-sm leading-6 text-slate-800 whitespace-pre-wrap">
              {model.reviewedMessage}
            </div>
            <p className="text-xs leading-5 text-slate-500">
              {model.recovery
                ? "This checks the saved send shown above using the same request."
                : "Each selected number receives a private WhatsApp message. This send will have its own delivery report."}
            </p>
            {model.error && <ErrorBanner message={model.error} />}
            {model.uncertain && (
              <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                <Link
                  href={ROUTES.dashboard.whatsappBroadcastHistory(
                    model.group.id,
                  )}
                  target="_blank"
                  className="font-medium underline"
                >
                  Open delivery history
                </Link>
                <label className="flex items-start gap-2 text-xs leading-5">
                  <input
                    type="checkbox"
                    checked={checkedHistory}
                    onChange={(event) =>
                      setCheckedHistory(event.target.checked)
                    }
                    className="mt-1 accent-blue-600"
                  />
                  I checked the earlier send and want to prepare a separate
                  message.
                </label>
                <Button
                  variant="secondary"
                  disabled={!checkedHistory}
                  onClick={model.startSeparateMessage}
                >
                  Prepare a separate message
                </Button>
              </div>
            )}
            <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
              <Button
                variant="secondary"
                onClick={() => model.setReviewing(false)}
                disabled={model.pending}
              >
                Back to editing
              </Button>
              <Button
                disabled={
                  Boolean(model.uncertain) || (!model.recovery && !model.ready)
                }
                isLoading={model.pending}
                onClick={() => void model.send(Boolean(model.recovery))}
              >
                <Send className="h-4 w-4" />
                {model.recovery
                  ? "Check send status"
                  : `Send ${model.count ?? model.selected.length} messages`}
              </Button>
            </div>
          </div>
        </DialogFrame>
      )}
    </div>
  );
}
