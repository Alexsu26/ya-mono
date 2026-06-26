from __future__ import annotations

from ya_agent_sdk.toolsets.core.pptx.assets import search_public_images


async def test_search_pexels_maps_asset_record(monkeypatch, httpx_mock) -> None:
    monkeypatch.setenv("YA_AGENT_PPTX_PEXELS_API_KEY", "pexels-key")
    monkeypatch.delenv("YA_AGENT_PPTX_UNSPLASH_ACCESS_KEY", raising=False)
    httpx_mock.add_response(
        url="https://api.pexels.com/v1/search?query=classroom&per_page=1",
        json={
            "photos": [
                {
                    "id": 123,
                    "alt": "Classroom",
                    "photographer": "Jane",
                    "url": "https://pexels.example/photo",
                    "src": {
                        "large": "https://images.example/classroom.jpg",
                        "medium": "https://images.example/thumb.jpg",
                    },
                }
            ]
        },
    )

    results = await search_public_images("classroom", limit=1)

    assert results[0].source == "pexels"
    assert results[0].license == "Pexels License"
    assert results[0].url == "https://images.example/classroom.jpg"


async def test_search_unsplash_maps_asset_record(monkeypatch, httpx_mock) -> None:
    monkeypatch.delenv("YA_AGENT_PPTX_PEXELS_API_KEY", raising=False)
    monkeypatch.setenv("YA_AGENT_PPTX_UNSPLASH_ACCESS_KEY", "unsplash-key")
    httpx_mock.add_response(
        url="https://api.unsplash.com/search/photos?query=park&per_page=1",
        json={
            "results": [
                {
                    "id": "abc",
                    "alt_description": "Park",
                    "description": None,
                    "links": {"html": "https://unsplash.example/photo"},
                    "urls": {"regular": "https://images.example/park.jpg", "small": "https://images.example/thumb.jpg"},
                    "user": {"name": "Alex"},
                }
            ]
        },
    )

    results = await search_public_images("park", limit=1)

    assert results[0].source == "unsplash"
    assert results[0].license == "Unsplash License"
    assert results[0].url == "https://images.example/park.jpg"


async def test_search_public_images_without_keys_returns_empty(monkeypatch, httpx_mock) -> None:
    monkeypatch.delenv("YA_AGENT_PPTX_PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("YA_AGENT_PPTX_UNSPLASH_ACCESS_KEY", raising=False)

    assert await search_public_images("demo") == []
    assert len(httpx_mock.get_requests()) == 0
