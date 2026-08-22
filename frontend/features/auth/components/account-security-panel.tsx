"use client";

import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Check, Copy, KeyRound, ShieldCheck } from "lucide-react";
import { Button, Card, CardContent, PasswordInput } from "@/components/ui";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { authApi } from "../api/auth.api";

export function AccountSecurityPanel() {
  const user = useAuthStore(selectUser);
  const clearSession = useAuthStore((state) => state.clearSession);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [codesCopied, setCodesCopied] = useState(false);

  const passwordChange = useMutation({
    mutationFn: () => authApi.changePassword(currentPassword, newPassword),
    onSuccess: async () => {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      await clearSession("logout", {
        revokeServerSession: false,
        loginReason: "password_changed",
      });
    },
  });
  const recoveryCodeRegeneration = useMutation({
    mutationFn: authApi.regenerateMfaRecoveryCodes,
    onSuccess: (codes) => {
      setRecoveryCodes(codes);
      setCodesCopied(false);
    },
  });

  const submitPasswordChange = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setValidationError(null);
    if (newPassword.length < 10 || !/[A-Z]/.test(newPassword) || !/[a-z]/.test(newPassword) || !/\d/.test(newPassword)) {
      setValidationError("Use at least 10 characters with uppercase, lowercase, and a number.");
      return;
    }
    if (newPassword !== confirmation) {
      setValidationError("The password confirmation does not match.");
      return;
    }
    if (currentPassword === newPassword) {
      setValidationError("Choose a password different from your current password.");
      return;
    }
    passwordChange.mutate();
  };

  return (
    <Card>
      <CardContent className="space-y-5 p-5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-base font-semibold text-slate-900">Account security</h2>
            <p className="text-sm text-slate-500">Manage your own password and recovery codes.</p>
          </div>
        </div>

        <form className="space-y-4" onSubmit={submitPasswordChange} noValidate>
          <PasswordInput
            id="security-current-password"
            label="Current password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
          />
          <PasswordInput
            id="security-new-password"
            label="New password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
          />
          <PasswordInput
            id="security-confirm-password"
            label="Confirm new password"
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            required
          />
          <p className="text-xs leading-5 text-slate-500">
            Changing your password revokes every browser session, including this one.
          </p>
          {(validationError || passwordChange.error) && (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {validationError ?? "The password could not be changed. Check your current password and try again."}
            </div>
          )}
          <Button
            type="submit"
            isLoading={passwordChange.isPending}
            disabled={!currentPassword || !newPassword || !confirmation || passwordChange.isPending}
            leftIcon={<KeyRound className="h-4 w-4" aria-hidden="true" />}
          >
            Change password
          </Button>
        </form>

        {user?.mfa_enabled && (
          <section className="space-y-3 border-t border-slate-100 pt-5" aria-labelledby="mfa-recovery-heading">
            <div>
              <h3 id="mfa-recovery-heading" className="text-sm font-semibold text-slate-900">MFA recovery codes</h3>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                Regenerating invalidates every older recovery code. A recent authenticator verification is required.
              </p>
            </div>
            {recoveryCodes.length > 0 && (
              <div className="space-y-3" role="status" aria-label="New recovery codes">
                <div className="grid grid-cols-2 gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 font-mono text-xs text-amber-950">
                  {recoveryCodes.map((code) => <span key={code}>{code}</span>)}
                </div>
                <p className="text-xs text-amber-800">Save these now. They are displayed only in this response.</p>
              </div>
            )}
            {recoveryCodeRegeneration.error && (
              <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                Recovery codes could not be regenerated.
              </div>
            )}
            {recoveryCodes.length > 0 ? (
              <Button
                type="button"
                variant="secondary"
                leftIcon={codesCopied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
                onClick={() => void navigator.clipboard.writeText(recoveryCodes.join("\n")).then(() => setCodesCopied(true))}
              >
                {codesCopied ? "Recovery codes copied" : "Copy recovery codes"}
              </Button>
            ) : (
              <Button
                type="button"
                variant="secondary"
                isLoading={recoveryCodeRegeneration.isPending}
                onClick={() => recoveryCodeRegeneration.mutate()}
              >
                Regenerate recovery codes
              </Button>
            )}
          </section>
        )}
      </CardContent>
    </Card>
  );
}
