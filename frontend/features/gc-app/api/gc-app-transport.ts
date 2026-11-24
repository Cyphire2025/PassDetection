import type { GcPage, GcPageParams } from "../types";
import type { PageEnvelope } from "./gc-app-wire.types";

export const ROOT = "/api/v1/gc-app/admin";
export const PAGE_SIZE = 20;
export const AGENCY_DIRECTORY_PAGE_SIZE = 100;
export const MAX_AGENCY_DIRECTORY_ITEMS = 5_000;

export function asPage<T>(data: PageEnvelope<T>, params: GcPageParams): GcPage<T> {
  if (Array.isArray(data)) {
    return {
      items: data,
      total: data.length,
      page: params.page,
      page_size: params.page_size,
      has_next: data.length === params.page_size,
    };
  }
  if ("offset" in data) {
    return {
      items: data.items,
      total: data.total,
      page: Math.floor(data.offset / data.limit) + 1,
      page_size: data.limit,
      has_next: data.offset + data.items.length < data.total,
    };
  }
  return data;
}

export function toOffsetParams(params: GcPageParams) {
  return {
    q: params.search || undefined,
    offset: (params.page - 1) * params.page_size,
    limit: params.page_size,
  };
}

export function agencyParams(agencyId: string | null, extra: Record<string, unknown> = {}) {
  return { ...extra, agency_id: agencyId ?? undefined };
}

export async function mapBounded<T, R>(items: T[], limit: number, mapper: (item: T) => Promise<R>): Promise<R[]> {
  const output = new Array<R>(items.length);
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      output[index] = await mapper(items[index]);
    }
  }));
  return output;
}
