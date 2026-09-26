"""Compatible legacy array endpoints share explicit work limits."""

from typing import Annotated

from fastapi import Query

MAX_PAGE_SIZE = 200
MAX_PAGE_OFFSET = 100_000
PageSize = Annotated[
    int,
    Query(
        ge=1, le=MAX_PAGE_SIZE, description="Maximum records returned. Continue with skip + limit."
    ),
]
PageOffset = Annotated[
    int,
    Query(
        ge=0,
        le=MAX_PAGE_OFFSET,
        description="Zero-based offset; bulk export uses its own endpoint.",
    ),
]
