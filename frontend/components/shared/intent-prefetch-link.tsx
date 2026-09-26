"use client";

import {
  useRef,
  type ComponentProps,
  type FocusEvent,
  type MouseEvent,
  type TouchEvent,
} from "react";
import Link from "next/link";
import type { Route } from "next";
import { useRouter } from "next/navigation";

type IntentPrefetchLinkProps<T extends string> = Omit<
  ComponentProps<typeof Link>,
  "href" | "prefetch"
> & {
  href: Route<T>;
};

/**
 * Large operational lists can contain hundreds of dynamic links. Prefetch only
 * after pointer, keyboard, or touch intent so navigation is warmed without
 * flooding the client cache for every row in the viewport.
 */
export function IntentPrefetchLink<T extends string>({
  href,
  onMouseEnter,
  onFocus,
  onTouchStart,
  ...props
}: IntentPrefetchLinkProps<T>) {
  const router = useRouter();
  const hasPrefetched = useRef(false);
  const prefetch = () => {
    if (hasPrefetched.current) return;
    hasPrefetched.current = true;
    router.prefetch(href);
  };

  return (
    <Link
      {...props}
      href={href}
      prefetch={false}
      onMouseEnter={(event: MouseEvent<HTMLAnchorElement>) => {
        prefetch();
        onMouseEnter?.(event);
      }}
      onFocus={(event: FocusEvent<HTMLAnchorElement>) => {
        prefetch();
        onFocus?.(event);
      }}
      onTouchStart={(event: TouchEvent<HTMLAnchorElement>) => {
        prefetch();
        onTouchStart?.(event);
      }}
    />
  );
}
