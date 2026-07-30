import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "Privacy Policy for Global Connect Travels services.",
  robots: { index: true, follow: true },
};

export default function PrivacyPolicyPage() {
  return (
    <article className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Privacy Policy</h1>
        <p className="mt-2 text-sm text-slate-600">
          Effective date: July 29, 2026
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Overview</h2>
        <p>
          Global Connect Travels provides tools for authorized staff to manage
          travel documents and related communications. This policy explains how
          information is handled when these services are used.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Information we process</h2>
        <p>
          We may process account information, contact details, travel records,
          uploaded documents, service activity, and technical logs required to
          operate and secure the service.
        </p>
        <p>
          If a user connects a Google or Microsoft account, the service may
          access the account email address, Gmail message metadata or Outlook
          message metadata, message content, and attachments that the user
          authorizes through Google or Microsoft. Mail access is read-only.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">How information is used</h2>
        <p>
          Information is used to identify relevant travel communications,
          retrieve travel documents, match documents to traveller records,
          support staff review, maintain security, and provide technical
          support. Connected-account data is not used for advertising.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Sharing</h2>
        <p>
          We do not sell personal information. Information may be shared only
          with authorized personnel, service providers needed to operate the
          platform, or when required by law. Service providers may process
          information only for the services they provide to us.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Google API data</h2>
        <p>
          Our use and transfer of information received from Google APIs adheres
          to the Google API Services User Data Policy, including the Limited Use
          requirements. Access is limited to the functions described in this
          policy and authorized by the user.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Storage and security</h2>
        <p>
          We use access controls, encrypted credential storage, secure network
          connections, and operational safeguards intended to protect
          information. No system can guarantee absolute security.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Retention and deletion</h2>
        <p>
          Information is retained only as long as reasonably required for the
          service, legal obligations, security, and record keeping. Users may
          disconnect a linked Google or Microsoft account to stop future
          access. Requests to access, correct, or delete information can be sent
          to the contact below.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Contact</h2>
        <p>
          Questions or privacy requests may be sent to{" "}
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
