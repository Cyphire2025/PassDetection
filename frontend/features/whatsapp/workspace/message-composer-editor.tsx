import Image from "next/image";
import { ImagePlus } from "lucide-react";
import { ComposerPreview, ComposerTextField } from "./composer-primitives";
import { fieldClass } from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";
import type { ComposerController } from "./message-composer";

export function MessageComposerEditor({ model }: { model: ComposerController }) {
  const definition = model.definition;
  return (<section
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
  </section>);
}
