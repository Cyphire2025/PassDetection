import { AuthHydrator } from "@/features/auth/components/auth-hydrator";

export default function CoordinatorLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AuthHydrator />
      {children}
    </>
  );
}
