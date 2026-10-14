/** Client hint mirrors API limits; the server remains the query authority. */
export function companySearchHint(value: string): string | undefined {
  const search = value.normalize("NFKC").trim();
  if (!search || /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(search)) return;
  const words = [...new Set(search.split(/\s+/))];
  if (words.some((word) => [...word].length < 2)) return "Enter at least 2 characters per name part.";
  if (search.length > 120 || words.length > 8 || words.some((word) => [...word].length > 32)) return "Use up to 8 name parts, with 2–32 characters each.";
}
