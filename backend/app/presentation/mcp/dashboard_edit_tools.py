"""Code-owned typed registrations for current dashboard edits."""

from typing import Annotated, Any

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from app.core.config.settings import Settings
from app.presentation.mcp.dashboard_edit_models import EDIT_MODELS
from app.presentation.mcp.dashboard_edit_operations import dashboard_edit_operation
from app.presentation.mcp.invocation import invoke_operation

EDIT_GUIDANCE = {
    "configure_group_link": "Edit one group's upload-link configuration at its inspected revision. Ask which collection fields, document methods and custom questions the user wants. Preserve unspecified fields. Broadcast linking is a separate additive tool. Existing QR expiry follows the group's travel dates. No messages are sent.",
    "update_menu_category": "Rename one menu category at its inspected revision in the explicitly selected agency or null platform library. Existing dishes and saved plan snapshots are retained.",
    "update_menu_dish": "Edit a dish name/notes/active status at current dish and category revisions. Saved plan snapshots are retained; this does not delete the dish.",
    "update_meal_plan": "Edit a saved meal plan name/start date at its inspected revision. Existing meals remain; no randomized regeneration occurs.",
    "update_meal_plan_entry": "Change one saved meal to an explicitly chosen active dish at inspected plan, category and dish revisions. Canonical no-repeat rules apply. The prior entry is retained in history.",
    "configure_rooming_hotel": "Edit one hotel stay at its inspected revision. Manual room counts are retired; use passenger selection and automatic allocation. No check-in or physical attendance is recorded.",
    "select_rooming_passengers": "Add the user's explicitly selected eligible passengers to a hotel. Inspect the current group/hotel allocation revisions first. Moving passengers can invalidate affected room plans: explain and obtain the user's approval. Prior selections and plans are retained in audit history. Existing check-ins block unsafe changes.",
    "set_rooming_vip": "Set the user's chosen passengers' VIP status at current allocation revisions. Explain any room-plan invalidation and obtain approval. Prior selections and plans are retained. No physical check-in occurs.",
    "allocate_rooming_rooms": "Allocate the hotel's selected passengers using the user's chosen priority fields and current allocation revisions. Explain any plan replacement and obtain approval. Canonical gender and eligibility rules apply; prior plans are retained. Never fabricate check-ins.",
}


def register_dashboard_edit_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    def register_one(name: str, model: type[BaseModel]) -> None:
        definition = dashboard_edit_operation(name)
        app.state.mcp_operations[name] = definition

        async def execute(
            change: BaseModel,
            idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
        ) -> dict[str, Any]:
            return await invoke_operation(
                app,
                settings,
                definition,
                idempotency_key=idempotency_key,
                payload=change.model_dump(mode="json", exclude_unset=True),
            )

        # The type and name come solely from this reviewed registry. They form
        # the SDK's real input schema; users cannot select an arbitrary handler.
        execute.__name__ = name
        execute.__annotations__["change"] = model
        execute.__doc__ = (
            EDIT_GUIDANCE[name]
            + " Reuse the same idempotency key and exact input after an uncertain response. Changed intent requires a new reviewed request."
        )
        server.tool(
            name=name,
            meta={"capability": "mcp:change"},
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )(execute)

    for name, model in EDIT_MODELS.items():
        register_one(name, model)
