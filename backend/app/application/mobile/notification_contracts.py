"""Stable notification counts and delivery policy constants."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnnouncementNotificationCounts:
    passengers: int = 0
    client_managers: int = 0
    coordinators: int = 0

    @property
    def total(self) -> int:
        return self.passengers + self.client_managers + self.coordinators


@dataclass(frozen=True, slots=True)
class DocumentChangeNotificationCounts:
    """Role-scoped, PII-free notification counts for a document mutation."""

    passengers: int = 0
    client_managers: int = 0
    coordinators: int = 0

    @property
    def total(self) -> int:
        return self.passengers + self.client_managers + self.coordinators


@dataclass(frozen=True, slots=True)
class CountdownNotificationCounts:
    """Bounded scheduler result without recipient or trip identifiers."""

    inserted: int = 0
    cancelled: int = 0
    groups_scanned: int = 0


_RECIPIENT_PAGE_SIZE = 250


_COUNTDOWN_CLEANUP_PAGE_SIZE = 1_000


_NOTIFICATION_TYPE = "group_announcement"


_COUNTDOWN_NOTIFICATION_TYPE = "trip_countdown"


_LOCK_SCREEN_TITLE = "Global Connect Travels update"


_COUNTDOWN_DAYS = (3, 2, 1)


_COUNTDOWN_TEMPLATES: dict[int, tuple[tuple[str, str], ...]] = {
    3: (
        ("Three days to go ✈️", "Shopping done, or is the suitcase still waiting?"),
        ("Your trip is almost here 🌍", "Time to finish the last-minute checklist."),
        ("Three sleeps left", "Tickets, outfits and excitement ready?"),
    ),
    2: (
        ("Two days left 🧳", "Your suitcase would like some attention."),
        ("Almost boarding time", "Pack the essentials and save space for memories."),
        ("Two days to go ✨", "Time to turn that packing list into an actual packed bag."),
    ),
    1: (
        ("Tomorrow is the day ✈️", "Keep your passport, visa and tickets close."),
        ("One more sleep", "Check your documents and charge your phone."),
        ("Adventure starts tomorrow 🌍", "Documents ready? Bags zipped? Let's go."),
    ),
}
