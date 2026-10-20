/** Bound browser audio operations that can otherwise remain pending forever. */
export async function audioDeadline<T>(operation: Promise<T>, milliseconds: number, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([operation, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}

export async function requireRunningAudio(context: AudioContext): Promise<void> {
  const message = "Browser audio is paused. Tap the microphone again to reconnect.";
  try {
    if (context.state !== "running") await audioDeadline(context.resume(), 3000, message);
    if (context.state !== "running") throw new Error(message);
  } catch { throw new Error(message); }
}
