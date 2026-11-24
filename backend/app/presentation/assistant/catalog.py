"""Task-oriented discovery over the assistant's fixed, observational readers."""

import importlib
import re
from collections.abc import Awaitable, Callable
from typing import Any, cast

from app.domain.entities.entities import User
from app.domain.mcp_dashboard_reads import DASHBOARD_READS, DashboardRead
from app.presentation.assistant.read_scope import view_allowed
from app.presentation.mcp.dashboard_read_tools import (
    dashboard_handler as reviewed_handler,
)
from app.presentation.mcp.dashboard_read_tools import (
    dashboard_parameters,
)
from app.presentation.mcp.dashboard_read_tools import (
    validate_dashboard_parameters as reviewed_parameters,
)


def dashboard_handler(definition: DashboardRead) -> Callable[..., Awaitable[Any]]:
    if definition.handler.startswith("@assistant_"):
        module = importlib.import_module("app.presentation.assistant.dashboard_adapters")
        return cast(Callable[..., Awaitable[Any]], getattr(module, definition.handler[1:]))
    return reviewed_handler(definition)


def validate_dashboard_parameters(definition: DashboardRead, parameters: dict[str, Any]) -> dict[str, Any]:
    return reviewed_parameters(definition, parameters, handler=dashboard_handler(definition))

# These website reads were absent from the MCP-oriented catalog. They use small
# first-party adapters; the remaining readers keep their reviewed implementations.
ASSISTANT_READS = {
    **DASHBOARD_READS,
    "dashboard_summary": DashboardRead("@assistant_dashboard_summary", frozenset({"dashboard"}),
        "Dashboard passport totals, pending review, confirmed, active upload links and recent passenger activity. Select agency context."),
    "whatsapp_groups": DashboardRead("@assistant_whatsapp_groups", frozenset({"whatsapp"}),
        "List active or archived WhatsApp broadcast groups/topics, their IDs, names, recipient and source traveller counts."),
    "whatsapp_message_topics": DashboardRead("@assistant_whatsapp_message_topics", frozenset({"whatsapp"}),
        "Available WhatsApp message topics/types and their configured fields: welcome, documents, invitations and trip updates. Does not send."),
    "companies": DashboardRead("@assistant_companies", frozenset({"manager"}),
        "Search the Companies / Clients directory, status and saved business details, with native cursor/page_size."),
    "company_summary": DashboardRead("@assistant_company_summary", frozenset({"manager"}),
        "Company / client totals: groups, traveller participation and returning travellers by company_id."),
    "company_groups": DashboardRead("@assistant_company_groups", frozenset({"manager"}),
        "Company / client trips, group dates and participant submission counts by company_id, with native cursor/page_size."),
}

# User language must lead to the roster, rather than only group configuration.
HINTS = {
    "passport_view": "people person participants members travellers travelers passengers roster headcount how many counts names list details",
    "passport_details": "people person participant member traveller traveler passenger personal details passport visa contact family",
    "tour_passengers": "people participants members travellers travelers passengers coordinator assignment",
    "whatsapp_groups": "active whatsapp topics groups broadcasts recipient counts audience",
    "whatsapp_tracking": "whatsapp people recipients members audience delivery statuses tracking",
    "whatsapp_message_topics": "whatsapp message topics types templates welcome update document",
    "group_links": "live active groups departures trips",
    "dashboard_summary": "dashboard overview statistics totals counts people pending confirmed",
    "companies": "companies company clients client business directory",
}


def data_catalog(query: str = "", *, offset: int = 0, actor: User | None = None) -> dict[str, Any]:
    terms = set(re.findall(r"\w+", query.casefold())) - {
        "the", "a", "an", "all", "are", "is", "in", "of", "for", "to", "my", "me", "show", "tell", "what", "can",
    }
    ranked: list[tuple[int, str, DashboardRead]] = []
    for name, definition in ASSISTANT_READS.items():
        if not view_allowed(actor, name):
            continue
        title = set(name.split("_"))
        hints = set(HINTS.get(name, "").split())
        text = set(re.findall(r"\w+", f"{definition.description} {' '.join(definition.sections)}".casefold()))
        score = 8 * len(terms & title) + 5 * len(terms & hints) + len(terms & text)
        if name == "whatsapp_groups" and "whatsapp" in terms and terms & {"active", "current", "live", "archived"}:
            score += 20
        if not terms or score or name == query.strip():
            ranked.append((score + (100 if name == query.strip() else 0), name, definition))
    ranked.sort(key=lambda row: -row[0])  # Stable ties preserve the reviewed catalog order.
    selected = ranked[offset:offset + 8]
    return {
        "views": [{"name": name, "description": definition.description,
                   "parameters": dashboard_parameters(definition, handler=dashboard_handler(definition))} for _, name, definition in selected],
        "matching_views": len(ranked),
        "has_more": len(ranked) > offset + 8,
        "next_offset": offset + 8 if len(ranked) > offset + 8 else None,
        "notice": "Search uses topic relevance, not record contents. No matches do not establish a lack of data access. Try people, WhatsApp, documents or an exact view name. Follow next_offset for more schemas.",
    }


def capability_guide(actor: User) -> dict[str, Any]:
    routes = {
        "group_people": ["passport_view", "passport_details", "passport_client_details", "tour_passengers"],
        "whatsapp": ["whatsapp_groups", "whatsapp_tracking", "whatsapp_broadcast_records", "whatsapp_message_topics"],
        "dashboard": ["dashboard_summary", "group_links", "global_search"],
        "documents": ["document_groups", "document_review", "document_delivery_summary"],
        "travel_operations": ["rooming_workspace", "menu_workspace", "tour_groups", "attendance_overview", "gc_itinerary"],
        "administration": ["companies", "company_groups", "managers", "staff_access", "platform_settings"],
        "email": ["email_operations_inbox", "email_message", "email_message_intelligence"],
    }
    return {
        "role": actor.role.value,
        "view_count": sum(view_allowed(actor, name) for name in ASSISTANT_READS),
        "areas": {area: visible for area, views in routes.items()
                  if (visible := [view for view in views if view_allowed(actor, view)])},
        "people_recipe": "Use passport_view with group_id and submission_filter=all. Its group_total/total count records; items contains passenger details. Projection total counts fields/items, NOT people. Follow references/data_path and website page/total_pages. passport_details reads an individual submission. Distinguish submissions, operational passengers and WhatsApp recipients.",
        "whatsapp_recipe": "whatsapp_groups with archived=false lists current broadcast groups/topics and counts. Use its broadcast ID for whatsapp_tracking or whatsapp_broadcast_records. whatsapp_message_topics lists message types instead. Client group IDs and broadcast IDs are different.",
        "access": "Current account's authorized dashboard observations, including personal passenger fields where allowed. No business writes, credentials, signed file URLs or external inbox/provider refreshes.",
    }
