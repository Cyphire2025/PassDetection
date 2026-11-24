import { useState, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import "../../app/globals.css";
import { PassportGroupSelectionToolbar } from "../../features/passports/components/passport-group-selection-toolbar";
import { usePassportGroupMenus } from "../../features/passports/components/use-passport-group-menus";

function Fixture() {
  const menus = usePassportGroupMenus();
  const [exports, setExports] = useState(0);
  const [search, setSearch] = useState("");
  const props = {
    ...menus,
    search, setSearch, setPage: () => {}, isFetching: false, isLoading: false,
    sortBy: "name", setSortBy: () => {}, submissionFilter: "all", setSubmissionFilter: () => {},
    sortOrder: "asc", setSortOrder: () => {}, selectionPreset: "", handleSelectionPreset: () => {},
    submissionsView: { total: 1 }, customSelectionCount: "", setCustomSelectionCount: () => {},
    selectedPassports: ["synthetic-selected"], documentFollowUp: { canManage: false },
    canEditDisplayName: false, canBulkStaffApprove: false, canPermanentlyDelete: false,
    exportSelected: { isPending: false, mutate: () => setExports((count) => count + 1) },
    exportSelectedImages: { isPending: false }, handleSelectedPassportDownload: () => {},
    bulkDelete: { isPending: false }, resetBulkSelection: () => {}, viewMode: "table", setViewMode: () => {},
  } as unknown as ComponentProps<typeof PassportGroupSelectionToolbar>;
  return (
    <main className="w-full p-4">
      <PassportGroupSelectionToolbar {...props} />
      <button type="button" className="mt-72">Outside action</button>
      <output aria-label="Synthetic exports">{exports}</output>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
