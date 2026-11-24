import type { UploadLinkResponse } from "../api/upload-links.api";

export function filterUploadLinks(links: UploadLinkResponse[], query: string) {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return links;
  return links.filter((link) =>
    [
      link.name,
      link.destination ?? "",
      link.package_name ?? "",
      ...link.departure_cities,
    ]
      .join(" ")
      .toLocaleLowerCase()
      .includes(normalized),
  );
}
