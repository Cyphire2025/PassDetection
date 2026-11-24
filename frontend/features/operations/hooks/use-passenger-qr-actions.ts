import { useRef, useState } from "react";
import { usePassengerQrLifecycle } from "./use-operations";

export function usePassengerQrActions(groupId: string) {
  const qrLifecycle = usePassengerQrLifecycle(groupId);
  const [generatedPayloads, setGeneratedPayloads] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingPassengerIds, setPendingPassengerIds] = useState<ReadonlySet<string>>(() => new Set());
  const pendingPassengerLocks = useRef(new Set<string>());

  const beginPassengerAction = (passengerId: string) => {
    pendingPassengerLocks.current.add(passengerId);
    setPendingPassengerIds(current => new Set(current).add(passengerId));
    setActionError(null);
  };
  const finishPassengerAction = (passengerId: string) => {
    pendingPassengerLocks.current.delete(passengerId);
    setPendingPassengerIds(current => {
      const next = new Set(current);
      next.delete(passengerId);
      return next;
    });
  };

  const revealToken = async (passengerId: string, regenerate: boolean) => {
    if (pendingPassengerLocks.current.has(passengerId)) return;
    if (regenerate && !window.confirm("Regenerate this QR? The previous printed code will stop working immediately.")) return;
    beginPassengerAction(passengerId);
    try {
      const result = await (regenerate
        ? qrLifecycle.regenerate.mutateAsync(passengerId)
        : qrLifecycle.generate.mutateAsync(passengerId));
      if (result.qr_payload) {
        setGeneratedPayloads((current) => ({ ...current, [passengerId]: result.qr_payload as string }));
      }
    } catch {
      setActionError("The QR action could not be completed. Refresh and try again.");
    } finally {
      finishPassengerAction(passengerId);
    }
  };

  const updateLifecycle = async (passengerId: string, action: "revoke" | "expire" | "activate" | "deactivate") => {
    if (pendingPassengerLocks.current.has(passengerId)) return;
    const warnings = {
      revoke: "Revoke this QR permanently? The passenger will need a newly generated code.",
      expire: "Expire this QR now? It will stop scanning immediately.",
      activate: "Activate this QR again? Any existing printed copy will become scannable.",
      deactivate: "Deactivate this QR? It can be activated again later.",
    };
    if (!window.confirm(warnings[action])) return;
    beginPassengerAction(passengerId);
    try {
      if (action === "revoke") await qrLifecycle.revoke.mutateAsync(passengerId);
      if (action === "expire") await qrLifecycle.expire.mutateAsync(passengerId);
      if (action === "activate") await qrLifecycle.setActive.mutateAsync({ passengerId, isActive: true });
      if (action === "deactivate") await qrLifecycle.setActive.mutateAsync({ passengerId, isActive: false });
      if (action === "revoke" || action === "expire") {
        setGeneratedPayloads((current) => {
          const next = { ...current };
          delete next[passengerId];
          return next;
        });
      }
    } catch {
      setActionError("The QR status could not be updated. Refresh and try again.");
    } finally {
      finishPassengerAction(passengerId);
    }
  };

  return { generatedPayloads, pendingPassengerIds, actionError, setActionError, revealToken, updateLifecycle };
}
