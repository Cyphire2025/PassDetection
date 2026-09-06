"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import styles from "./auth-experience.module.css";

const FILM = "/assets/branding/global-connect/journey-film/journey-film-web.mp4?v=pavilion-v3";
const POSTER = "/assets/branding/global-connect/journey-film/journey-film-poster.jpg?v=pavilion-v3";
const SERVICES = ["Corporate travel", "Hotels & hospitality", "Conferences & events"];
type NetworkPreference = EventTarget & { saveData?: boolean };

function connectionPreference() {
  return (navigator as Navigator & { connection?: NetworkPreference }).connection;
}
function motionPreference() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches || Boolean(connectionPreference()?.saveData);
}
function subscribeToMotionPreference(onChange: () => void) {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  const connection = connectionPreference();
  media.addEventListener("change", onChange);
  connection?.addEventListener("change", onChange);
  return () => {
    media.removeEventListener("change", onChange);
    connection?.removeEventListener("change", onChange);
  };
}
const serverMotionPreference = () => true;

export function CompanyJourneyFilm() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const motionLimited = useSyncExternalStore(subscribeToMotionPreference, motionPreference, serverMotionPreference);
  const [mediaUnavailable, setMediaUnavailable] = useState(false);
  const [chapter, setChapter] = useState(0);
  const shouldLoadVideo = !motionLimited && !mediaUnavailable;

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !shouldLoadVideo) return;
    let inView = false;
    let disposed = false;
    const reconcilePlayback = () => {
      if (disposed) return;
      if (document.hidden || !inView) video.pause();
      else void video.play().catch((error: unknown) => {
        // Hiding the film can interrupt a pending play request. Keep that
        // interruption resumable; blocked or failed playback uses the poster.
        if (!disposed && !(error instanceof DOMException && error.name === "AbortError")) {
          setMediaUnavailable(true);
        }
      });
    };
    const observer = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      reconcilePlayback();
    }, { threshold: 0.15 });
    observer.observe(video);
    document.addEventListener("visibilitychange", reconcilePlayback);
    return () => {
      disposed = true;
      observer.disconnect();
      document.removeEventListener("visibilitychange", reconcilePlayback);
      video.pause();
    };
  }, [shouldLoadVideo]);

  return (
    <figure className={styles.journey} aria-label="The Global Connect journey">
      <div className={styles.filmViewport}>
        <video
          ref={videoRef}
          src={shouldLoadVideo ? FILM : undefined}
          poster={POSTER}
          width={1600}
          height={1000}
          muted
          loop
          playsInline
          preload={shouldLoadVideo ? "metadata" : "none"}
          aria-hidden="true"
          className={styles.film}
          onError={() => setMediaUnavailable(true)}
          onTimeUpdate={(event) => {
            const time = event.currentTarget.currentTime;
            setChapter(time < 6.5 || time >= 20 ? 0 : time < 13 ? 1 : 2);
          }}
        />
      </div>
      <figcaption className="sr-only">
        A continuous animated journey from international flights to destination hospitality,
        conferences and shared experiences, created for Global Connect Travels.
      </figcaption>
      <div className={styles.filmToolbar}>
        <p className={styles.filmSignature}><span />One team. Every detail.</p>
      </div>
      <ol className={styles.services} aria-label="Our expertise">
        {SERVICES.map((service, index) => (
          <li key={service} data-active={index === chapter && shouldLoadVideo}>
            <span className={styles.serviceNumber} aria-hidden="true">0{index + 1}</span><span>{service}</span>
          </li>
        ))}
      </ol>
    </figure>
  );
}
