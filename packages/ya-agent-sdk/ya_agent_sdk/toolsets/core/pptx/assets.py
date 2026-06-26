"""Public image metadata search for PPTX visual slots."""

from __future__ import annotations

import httpx

from ya_agent_sdk._config import AgentSettings
from ya_agent_sdk.toolsets.core.pptx.schemas import AssetRecord


async def search_public_images(query: str, *, limit: int = 3) -> list[AssetRecord]:
    settings = AgentSettings()
    if not settings.pptx_asset_search_enabled:
        return []

    results: list[AssetRecord] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        if settings.pptx_pexels_api_key:
            results.extend(
                await _search_pexels(
                    client,
                    query=query,
                    api_key=settings.pptx_pexels_api_key,
                    limit=limit,
                )
            )
        if len(results) < limit and settings.pptx_unsplash_access_key:
            results.extend(
                await _search_unsplash(
                    client,
                    query=query,
                    access_key=settings.pptx_unsplash_access_key,
                    limit=limit - len(results),
                )
            )
    return results[:limit]


async def _search_pexels(
    client: httpx.AsyncClient,
    *,
    query: str,
    api_key: str,
    limit: int,
) -> list[AssetRecord]:
    response = await client.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": limit},
        headers={"Authorization": api_key},
    )
    response.raise_for_status()
    payload = response.json()
    records: list[AssetRecord] = []
    for photo in payload.get("photos", []):
        src = photo.get("src") or {}
        records.append(
            AssetRecord(
                id=str(photo.get("id")) if photo.get("id") is not None else None,
                source="pexels",
                title=photo.get("alt"),
                query=query,
                url=src.get("large") or src.get("original"),
                thumbnail_url=src.get("medium") or src.get("small"),
                author=photo.get("photographer"),
                license="Pexels License",
                metadata={"page_url": photo.get("url")},
            )
        )
    return records


async def _search_unsplash(
    client: httpx.AsyncClient,
    *,
    query: str,
    access_key: str,
    limit: int,
) -> list[AssetRecord]:
    response = await client.get(
        "https://api.unsplash.com/search/photos",
        params={"query": query, "per_page": limit},
        headers={"Authorization": f"Client-ID {access_key}"},
    )
    response.raise_for_status()
    payload = response.json()
    records: list[AssetRecord] = []
    for photo in payload.get("results", []):
        urls = photo.get("urls") or {}
        user = photo.get("user") or {}
        links = photo.get("links") or {}
        records.append(
            AssetRecord(
                id=photo.get("id"),
                source="unsplash",
                title=photo.get("alt_description") or photo.get("description"),
                query=query,
                url=urls.get("regular") or urls.get("full"),
                thumbnail_url=urls.get("small") or urls.get("thumb"),
                author=user.get("name"),
                license="Unsplash License",
                metadata={"page_url": links.get("html")},
            )
        )
    return records
