"""Roster view pagination with explicit projection boundaries."""

from __future__ import annotations

from .submission_view_types import DuplicateClusterPage, SubmissionViewEntry


def _paginate_blocks(
    blocks: list[list[SubmissionViewEntry]],
    page_size: int,
) -> list[list[SubmissionViewEntry]]:
    pages: list[list[SubmissionViewEntry]] = []
    current: list[SubmissionViewEntry] = []
    for block in blocks:
        if current and len(current) + len(block) > page_size:
            pages.append(current)
            current = []
        # Normal sets remain together. Oversized sets continue onto bounded
        # pages; retaining every row must never disable the hydration limit.
        for offset in range(0, len(block), page_size):
            current.extend(block[offset : offset + page_size])
            if len(current) == page_size:
                pages.append(current)
                current = []
    if current:
        pages.append(current)
    return pages


def _all_page_clusters(
    pages: list[list[SubmissionViewEntry]],
) -> tuple[tuple[DuplicateClusterPage, ...], ...]:
    bounds: dict[str, list[int]] = {}
    visible: list[dict[str, list[SubmissionViewEntry]]] = []
    for number, entries in enumerate(pages, start=1):
        current: dict[str, list[SubmissionViewEntry]] = {}
        for entry in entries:
            cluster_id = entry.duplicate_cluster_id
            if cluster_id is not None:
                bound = bounds.setdefault(cluster_id, [number, number, 0])
                bound[1], bound[2] = number, bound[2] + 1
                current.setdefault(cluster_id, []).append(entry)
        visible.append(current)
    return tuple(
        tuple(
            DuplicateClusterPage(
                cluster_id=cluster_id,
                total_members=entries[0].duplicate_cluster_size,
                matching_members=bounds[cluster_id][2],
                visible_member_ids=tuple(entry.submission.id for entry in entries),
                first_page=bounds[cluster_id][0],
                last_page=bounds[cluster_id][1],
            )
            for cluster_id, entries in current.items()
        )
        for current in visible
    )
