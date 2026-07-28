import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Terms of Service for Global Connect Travels services.",
  robots: { index: true, follow: true },
};

export default function TermsPage() {
  return (
    <article className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Terms of Service</h1>
        <p className="mt-2 text-sm text-slate-600">
          Effective date: July 29, 2026
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Using the service</h2>
        <p>
          These terms apply to the Global Connect Travels travel-document and
          communication services. By using the service, you agree to these
          terms and confirm that you are authorized to use the account and
          information you provide.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Accounts and authorization</h2>
        <p>
          Users are responsible for protecting their login details and for all
          authorized activity under their accounts. A connected Google account
          may be accessed only after the account holder grants permission
          through Google. That permission can be revoked through the service or
          the user&apos;s Google Account settings.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Acceptable use</h2>
        <p>
          The service may be used only for lawful travel operations. Users must
          not access information without permission, interfere with the
          service, upload harmful content, misuse personal information, or use
          the service in a way that violates applicable law or third-party
          rights.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Travel information</h2>
        <p>
          Users remain responsible for reviewing passport, visa, ticket, and
          other travel information before relying on it. Automated extraction
          and matching can require human review and should not be treated as
          legal, immigration, or travel advice.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Service availability</h2>
        <p>
          We work to keep the service available and secure, but uninterrupted
          or error-free operation is not guaranteed. Features may be changed,
          suspended, or discontinued when reasonably necessary for security,
          maintenance, legal compliance, or business operations.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Responsibility</h2>
        <p>
          To the extent permitted by law, Global Connect Travels is not liable
          for indirect or consequential loss arising from service interruption,
          inaccurate user-provided information, third-party services, or use
          outside the purposes described in these terms.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Changes</h2>
        <p>
          These terms may be updated when the service or legal requirements
          change. The effective date above will be updated when material
          revisions are published.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Contact</h2>
        <p>
          Questions about these terms may be sent to{" "}
          <a
            className="text-blue-700 underline"
            href="mailto:yogesh.gctravels@gmail.com"
          >
            yogesh.gctravels@gmail.com
          </a>
          .
        </p>
      </section>
    </article>
  );
}
