import type { Metadata } from "next";
import Image from "next/image";
import { ArrowUpRight } from "lucide-react";
import { CompanyJourneyFilm } from "@/features/auth/components/company-journey-film";
import styles from "@/features/auth/components/auth-experience.module.css";

export const metadata: Metadata = { title: "Sign In" };

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.shell} data-auth-experience>
      <div className={styles.access}>
        <div className={styles.paperRoutes} aria-hidden="true" />
        <main id="main-content" className={styles.signIn}>
          <div className={styles.formArea}>{children}</div>
        </main>
        <footer className={styles.accessFooter}>
          <a href="https://gctravels.in/" target="_blank" rel="noopener noreferrer" className={styles.companyLink}>
            Discover Global Connect<ArrowUpRight size={14} aria-hidden="true" />
          </a>
          <p>© {new Date().getFullYear()} Global Connect Travels Private Limited</p>
        </footer>
      </div>
      <aside className={styles.story} aria-labelledby="company-journey-heading">
        <div className={styles.wingArchitecture} aria-hidden="true" />
        <div className={styles.storyHeader}>
          <a href="/login" className={styles.storyBrand} aria-label="Global Connect — sign in">
            <span className={styles.storyLogoFrame}>
              <Image src="/assets/branding/global-connect/globalconnect-logo-removebg-preview.png"
                alt="Global Connect Travels Private Limited" width={612} height={408}
                sizes="(max-width: 899px) 176px, 310px" priority className={styles.storyLogo} />
            </span>
          </a>
          <span className={styles.brandDescriptor}>TRAVEL. PEOPLE. EXPERIENCES.</span>
        </div>
        <div className={styles.storyIntroduction}>
          <p className={styles.eyebrow}><span />CORPORATE TRAVEL &amp; MICE</p>
          <h2 id="company-journey-heading" className={styles.headline}>
            Move people.<br /><span>Create moments.</span>
          </h2>
          <p className={styles.storyDescription}>
            From the first departure<br className={styles.mobileBreak} /> to the final applause.
          </p>
        </div>
        <CompanyJourneyFilm />
      </aside>
    </div>
  );
}
