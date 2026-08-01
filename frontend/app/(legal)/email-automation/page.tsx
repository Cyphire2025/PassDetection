import type { Metadata } from "next";
import Link from "next/link";

const APP_NAME = "Global Connect Travels Email Automation";
const APP_URL = "https://tech.gctravels.com/email-automation";
const APP_DESCRIPTION =
  "Global Connect Travels Email Automation helps authorized travel staff securely review travel-related Gmail and Microsoft Outlook messages and attachments and organize them with traveller records.";

export const metadata: Metadata = {
  applicationName: APP_NAME,
  title: { absolute: APP_NAME },
  description: APP_DESCRIPTION,
  alternates: { canonical: APP_URL },
  manifest: "/email-automation.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: APP_NAME,
  },
  openGraph: {
    type: "website",
    url: APP_URL,
    siteName: APP_NAME,
    title: APP_NAME,
    description: APP_DESCRIPTION,
  },
  robots: { index: true, follow: true },
};

export default function EmailAutomationPage() {
  return (
    <article className="space-y-8">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-blue-700">
          Global Connect Travels
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">
          Global Connect Travels Email Automation
        </h1>
        <p className="mt-4 text-lg leading-8 text-slate-700">
          A secure internal travel-operations tool that helps authorized staff
          process travel documents received through connected Gmail and
          Microsoft Outlook inboxes.
        </p>
        <p className="mt-3 text-slate-700">
          This public application-information page is available without signing
          in.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Purpose of the application</h2>
        <p>
          The application monitors Gmail or Microsoft Outlook accounts
          connected by their owners, identifies travel-related messages,
          retrieves relevant attachments, and helps match those documents to
          traveller and group records. Staff can review results before taking
          action.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Google account access</h2>
        <p>
          A Gmail account is accessed only after its owner grants permission
          through Google OAuth. The application requests read-only Gmail access
          to review message metadata, message content, and attachments needed
          for travel-document processing. It does not send, edit, or delete
          email.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Microsoft account access</h2>
        <p>
          A Microsoft 365, Outlook, or Hotmail account is accessed only after
          its owner grants permission through Microsoft OAuth. The application
          requests delegated read-only mail access and basic profile access to
          identify the connected mailbox. It does not send, edit, or delete
          email.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">How the information is used</h2>
        <p>
          Authorized travel staff use the information to organize documents
          such as visas and flight tickets, associate them with the correct
          traveller, and resolve items that need manual review. Google user data
          is not sold or used for advertising.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">User control</h2>
        <p>
          Users can permanently remove a Gmail or Microsoft Outlook account
          and its attributable stored integration data from the application.
          They can also revoke access at any time from their Google Account or
          Microsoft Account permissions.
          Questions and data requests may be sent to{" "}
          <a
            className="text-blue-700 underline"
            href="mailto:yogesh.gctravels@gmail.com"
          >
            yogesh.gctravels@gmail.com
          </a>
          .
        </p>
      </section>

      <section className="border-t border-slate-200 pt-6">
        <h2 className="text-xl font-semibold">Policies</h2>
        <p className="mt-3 text-slate-700">
          Review our{" "}
          <Link
            className="text-blue-700 underline"
            href="https://tech.gctravels.com/privacy-policy"
          >
            Privacy Policy
          </Link>{" "}
          and{" "}
          <Link
            className="text-blue-700 underline"
            href="https://tech.gctravels.com/terms"
          >
            Terms of Service
          </Link>
          .
        </p>
      </section>
    </article>
  );
}
