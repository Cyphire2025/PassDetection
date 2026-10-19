import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { AssistantConfiguration, ModelCatalog } from "../settings-api";
import { AssistantModelSettings } from "./assistant-model-settings";

const mocks = vi.hoisted(() => ({ models: vi.fn() }));
vi.mock("../settings-api", () => ({ aiSettingsApi: mocks }));

const configuration: AssistantConfiguration = {
  enabled: true, allowed_roles: [], allowed_user_ids: [], provider: "gemini",
  gemini_model: "gemini-3.8-flash", gemini_live_model: "gemini-3.8-live", gemini_image_model: "gemini-3.1-flash-image",
  gemini_voice: "Zephyr", reasoning_effort: "high", openai_reasoning_effort: "medium", openai_speech_model: "", openai_voice: "marin",
  usage_limits: { daily_voice_chats: 30, voice_connection_minutes: 10, daily_requests: 200, daily_images: 12, daily_uploads: 80, daily_speech_requests: 300 },
};
const catalog: ModelCatalog = {
  revision: 1, observed_at: "2026-10-19T00:00:00Z", providers: [], models: [
    { id: "gemini:gemini-3.8-flash", model: "gemini-3.8-flash", label: "Gemini Flash", provider: "gemini", kind: "chat", available: true, reasoning: ["low", "medium", "high"], voices: [] },
    { id: "openai:gpt-4.1", model: "gpt-4.1", label: "GPT-4.1", provider: "openai", kind: "chat", available: true, reasoning: [], voices: [] },
    { id: "gemini:gemini-3.8-live", model: "gemini-3.8-live", label: "Gemini Live", provider: "gemini", kind: "voice", available: true, reasoning: [], voices: [{ id: "Zephyr", label: "Zephyr", appearance: "female" }, { id: "Puck", label: "Puck", appearance: "male" }] },
    { id: "openai:gpt-realtime-2.1", model: "gpt-realtime-2.1", label: "GPT Realtime", provider: "openai", kind: "voice", available: true, reasoning: ["low", "medium", "high"], voices: [{ id: "marin", label: "Marin", appearance: "female" }, { id: "cedar", label: "Cedar", appearance: "male" }] },
  ],
};
function Form() {
  const [value, setValue] = useState(configuration);
  return <><AssistantModelSettings value={value} onChange={setValue} revision={1} /><output data-testid="saved">{JSON.stringify(value)}</output></>;
}
beforeEach(() => { mocks.models.mockReset().mockResolvedValue(catalog); });

it("does not offer incompatible reasoning and resets reasoning when switching models", async () => {
  render(<Form />);
  const user = userEvent.setup();
  const chat = screen.getByRole("combobox", { name: "Chat & document model" });
  await waitFor(() => expect(chat).toBeEnabled());
  await user.selectOptions(screen.getByRole("combobox", { name: "Chat reasoning" }), "medium");
  await user.selectOptions(chat, "openai:gpt-4.1");
  expect(screen.getByRole("combobox", { name: "Chat reasoning" })).toBeDisabled();
  expect(JSON.parse(screen.getByTestId("saved").textContent!).chat_reasoning).toBe("");
  await user.selectOptions(chat, "gemini:gemini-3.8-flash");
  expect(screen.getByRole("combobox", { name: "Chat reasoning" })).toHaveValue("");
  expect(screen.queryByRole("combobox", { name: "Provider mode" })).not.toBeInTheDocument();
});

it("switches valid voice lists and saves the selected presentation", async () => {
  render(<Form />);
  const user = userEvent.setup();
  const model = screen.getByRole("combobox", { name: "Native voice model" });
  await waitFor(() => expect(model).toBeEnabled());
  await user.selectOptions(model, "openai:gpt-realtime-2.1");
  const voice = screen.getByRole("combobox", { name: "Voice" });
  expect(voice).toHaveValue("marin");
  expect(screen.queryByRole("option", { name: "Puck · Male" })).not.toBeInTheDocument();
  await user.selectOptions(voice, "cedar");
  expect(JSON.parse(screen.getByTestId("saved").textContent!).voice_presentation).toBe("male");
  expect(screen.getByRole("combobox", { name: "Voice reasoning" })).toHaveValue("low");
  await user.selectOptions(model, "gemini:gemini-3.8-live");
  expect(voice).toHaveValue("Zephyr");
  expect(screen.getByRole("combobox", { name: "Voice reasoning" })).toBeDisabled();
});

it("preserves selections after discovery failure and lets the administrator retry", async () => {
  mocks.models.mockRejectedValueOnce(new Error("offline"));
  render(<Form />);
  await screen.findByRole("alert");
  expect(screen.getByRole("combobox", { name: "Chat & document model" })).toHaveValue("gemini:gemini-3.8-flash");
  expect(screen.getByRole("combobox", { name: "Voice" })).toHaveValue("Zephyr");
  expect(screen.getByRole("combobox", { name: "Voice" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Refresh available models" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(screen.getByRole("combobox", { name: "Voice" })).toBeEnabled();
});
