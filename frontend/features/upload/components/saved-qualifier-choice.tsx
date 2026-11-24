import { Button } from "@/components/ui/button";

export function SavedQualifierChoice({ loading, disabled, error, onEdit }: {
  loading: boolean;
  disabled: boolean;
  error?: string;
  onEdit: () => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 rounded-xl bg-blue-50 p-3 text-sm text-blue-900">
        <span>Qualifier relationship saved</span>
        <Button type="button" variant="secondary" disabled={disabled} onClick={onEdit}>
          {loading ? "Loading relationship…" : "Change"}
        </Button>
      </div>
      {error && <p role="alert" className="text-sm text-amber-800">{error}</p>}
    </div>
  );
}
