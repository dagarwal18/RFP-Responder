import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from rfp_automation.api.routes import rfp_router, health_router, _runs, _document_cache
from fastapi import FastAPI

app = FastAPI()
app.include_router(health_router)
app.include_router(rfp_router, prefix="/api/rfp")

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_caches():
    """Clear memory stores before each test."""
    _runs.clear()
    _document_cache.clear()
    yield
    _runs.clear()
    _document_cache.clear()

def test_upload_rfp_cache_miss_runs_pipeline():
    """Test that a new file starts the pipeline thread and returns RUNNING."""
    file_content = b"New RFP Content"
    
    with patch("rfp_automation.api.routes.threading.Thread") as mock_thread:
        response = client.post(
            "/api/rfp/upload",
            files={"file": ("test.pdf", file_content, "application/pdf")}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "RUNNING"
        assert "rfp_id" in data
        assert "Pipeline started" in data["message"]
        
        # Verify thread was started
        mock_thread.return_value.start.assert_called_once()
        
        # Verify hash was NOT in cache
        file_hash = hashlib.sha256(file_content).hexdigest()
        assert file_hash not in _document_cache

def test_upload_rfp_cache_hit_returns_cached_result():
    """Test that uploading a file with a matching hash clones the previous result."""
    file_content = b"Cached RFP Content"
    file_hash = hashlib.sha256(file_content).hexdigest()
    
    # Pre-populate cache and runs with a successful past run
    old_rfp_id = "RFP-PREVIOUS"
    _document_cache[file_hash] = old_rfp_id
    _runs[old_rfp_id] = {
        "rfp_id": old_rfp_id,
        "filename": "old.pdf",
        "status": "COMPLETED",
        "result": {"fake_data": 123},
        "pipeline_log": [{"status": "Done"}],
        "started_at": "2024-01-01T00:00:00Z"
    }

    with patch("rfp_automation.api.routes.threading.Thread") as mock_thread:
        response = client.post(
            "/api/rfp/upload",
            files={"file": ("test.pdf", file_content, "application/pdf")}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # It should instantly be COMPLETED
        assert data["status"] == "COMPLETED"
        new_rfp_id = data["rfp_id"]
        assert new_rfp_id != old_rfp_id  # Should have a new unique ID
        assert "Cache hit" in data["message"]
        
        # Verify thread was NEVER started
        mock_thread.assert_not_called()
        
        # Verify the new run cloned the data
        assert new_rfp_id in _runs
        new_run = _runs[new_rfp_id]
        assert new_run["status"] == "COMPLETED"
        assert new_run["result"] == {"fake_data": 123}
        assert new_run["filename"] == "test.pdf"  # Updates to the new filename
        
def test_upload_rfp_ignores_failed_cache():
    """If the cached run was FAILED, it should run normally again."""
    file_content = b"Failed RFP Content"
    file_hash = hashlib.sha256(file_content).hexdigest()
    
    # Pre-populate cache with a FAILED run
    old_rfp_id = "RFP-FAILED"
    _document_cache[file_hash] = old_rfp_id
    _runs[old_rfp_id] = {
        "rfp_id": old_rfp_id,
        "status": "FAILED",
        "result": None,
    }

    with patch("rfp_automation.api.routes.threading.Thread") as mock_thread:
        response = client.post(
            "/api/rfp/upload",
            files={"file": ("test.pdf", file_content, "application/pdf")}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "RUNNING"
        
        # Thread SHOULD start because cache was deeply flawed/failed
        mock_thread.return_value.start.assert_called_once()
