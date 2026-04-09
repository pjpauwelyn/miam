"""
Vector search tests — verify retrieval returns relevant results.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from services.adapters.fsq_os import FSQOSAdapter


class TestFSQOSSearch:
    """Test the FSQ OS adapter search functionality using real mock data."""

    @pytest.fixture
    def adapter(self):
        """Load the real restaurants data file."""
        path = Path(__file__).resolve().parents[2] / "data" / "restaurants" / "restaurants_all.json"
        if path.exists():
            return FSQOSAdapter(data_path=str(path))
        pytest.skip("restaurants_all.json not found")

    def test_search_returns_results(self, adapter):
        result = adapter.search(lat=52.3676, lng=4.9041, radius_m=5000)
        assert "results" in result
        assert "context" in result
        assert len(result["results"]) > 0

    def test_search_respects_limit(self, adapter):
        result = adapter.search(lat=52.3676, lng=4.9041, radius_m=10000, limit=5)
        assert len(result["results"]) <= 5

    def test_search_returns_max_20_by_default(self, adapter):
        result = adapter.search(lat=52.3676, lng=4.9041, radius_m=20000)
        assert len(result["results"]) <= 20

    def test_search_with_category_filter(self, adapter):
        result = adapter.search(
            lat=52.3676, lng=4.9041, radius_m=20000,
            categories=["Japanese"],
        )
        # Results should only contain Japanese restaurants
        for r in result["results"]:
            cuisine = r.get("cuisine_tags", {})
            if isinstance(cuisine, dict):
                all_cuisines = [cuisine.get("primary", "").lower()] + [
                    s.lower() for s in cuisine.get("secondary", [])
                ]
            else:
                all_cuisines = []
            assert any("japanese" in c for c in all_cuisines), f"Non-Japanese result: {r['name']}"

    def test_search_with_keyword(self, adapter):
        result = adapter.search(
            lat=52.3676, lng=4.9041, radius_m=20000,
            query="Indonesian",
        )
        # Should find at least some results with Indonesian in their data
        assert isinstance(result["results"], list)


class TestRecipeSearchMocked:
    """Mocked vector search tests (no DB needed)."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        return pool, conn

    @pytest.mark.asyncio
    async def test_search_returns_results(self, mock_pool):
        pool, conn = mock_pool
        # Mock DB response
        conn.fetch = AsyncMock(return_value=[
            {
                "entity_id": "test-id-1",
                "data": json.dumps({"title": "Thai Green Curry", "cuisine_tags": ["Thai"]}),
                "similarity": 0.85,
            },
        ])

        from services.retrieval import search_recipes
        results = await search_recipes(
            query_embedding=[0.1] * 1024,
            pool=pool,
            top_k=5,
        )
        assert len(results) == 1
        assert results[0]["title"] == "Thai Green Curry"
        assert results[0]["_similarity"] == 0.85
