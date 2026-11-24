export {
  type PassportGroupViewMode,
  type PassportGroupViewState,
  type PassportDetailNavigationState,
  parsePassportGroupViewState,
  buildPassportGroupHref,
  buildPassportDetailNavigationHref,
  parsePassportDetailNavigation
} from "./passport-navigation-routes";
export { type StoredPassportNavigationContext, storePassportNavigationContext, readPassportNavigationContext } from "./passport-navigation-storage";


export function createPassportNavigationToken() {
  if (typeof window === "undefined" || !window.crypto?.randomUUID) return null;
  return window.crypto.randomUUID();
}

export function isPassportNavigationKeyboardTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return true;
  const role = target.getAttribute("role");
  return role === "textbox" || role === "combobox" || role === "spinbutton";
}
