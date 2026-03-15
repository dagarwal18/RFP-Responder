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


@pytest.fixture
def review_run():
    rfp_id = "RFP-REVIEW-001"
    _runs[rfp_id] = {
        "rfp_id": rfp_id,
        "filename": "review.pdf",
        "status": "AWAITING_HUMAN_VALIDATION",
        "current_agent": "H1_HUMAN_VALIDATION",
        "started_at": "2024-01-01T00:00:00Z",
        "pipeline_log": [],
        "result": {
            "review_package": {
                "review_id": "REV-001",
                "status": "PENDING",
                "source_sections": [
                    {
                        "section_id": "SRC-01",
                        "title": "Technical Requirements",
                        "domain": "source",
                        "paragraphs": [
                            {
                                "paragraph_id": "SRC-01:P1",
                                "text": "The platform must support SSO.",
                                "page_start": 1,
                                "page_end": 1,
                            }
                        ],
                    }
                ],
                "response_sections": [
                    {
                        "section_id": "SEC-01",
                        "title": "Technical Solution",
                        "domain": "response",
                        "paragraphs": [
                            {
                                "paragraph_id": "SEC-01:P1",
                                "text": "We provide secure identity integration.",
                                "page_start": 0,
                                "page_end": 0,
                            }
                        ],
                    }
                ],
                "comments": [],
                "decision": {
                    "decision": None,
                    "reviewer": "",
                    "summary": "",
                    "rerun_from": "",
                    "submitted_at": None,
                },
                "validation_summary": "Decision: PASS.",
                "commercial_summary": "",
                "legal_summary": "",
                "total_comments": 0,
                "open_comment_count": 0,
            }
        },
    }
    return rfp_id


def test_get_review_package(review_run):
    response = client.get(f"/api/rfp/{review_run}/review")

    assert response.status_code == 200
    data = response.json()
    assert data["rfp_id"] == review_run
    assert data["review_package"]["review_id"] == "REV-001"
    assert len(data["review_package"]["source_sections"]) == 1


def test_request_changes_requires_comment(review_run):
    response = client.post(
        f"/api/rfp/{review_run}/review/decision",
        json={"decision": "REQUEST_CHANGES", "reviewer": "Alex"},
    )

    assert response.status_code == 400
    assert "At least one open comment" in response.json()["detail"]


def test_request_changes_starts_rerun_from_target(review_run):
    comment = {
        "comment_id": "REV-CMT-1",
        "anchor": {
            "anchor_level": "paragraph",
            "domain": "response",
            "section_id": "SEC-01",
            "section_title": "Technical Solution",
            "paragraph_id": "SEC-01:P1",
            "excerpt": "We provide secure identity integration.",
        },
        "comment": "Be more explicit about SSO support.",
        "severity": "high",
        "rerun_hint": "auto",
        "status": "open",
        "author": "Alex",
        "created_at": "2026-03-16T00:00:00Z",
    }

    with patch("rfp_automation.persistence.checkpoint.load_checkpoint_up_to", return_value={"tracking_rfp_id": review_run}) as mock_load, \
         patch("rfp_automation.api.routes._start_rerun_job") as mock_start:
        response = client.post(
            f"/api/rfp/{review_run}/review/decision",
            json={
                "decision": "REQUEST_CHANGES",
                "reviewer": "Alex",
                "summary": "Please tighten the technical section.",
                "comments": [comment],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RUNNING"
    assert data["rerun_from"] == "c2_requirement_writing"
    mock_load.assert_called_once_with(review_run, "c2_requirement_writing")
    mock_start.assert_called_once()
    injected_checkpoint = mock_start.call_args.args[2]
    assert injected_checkpoint["review_package"]["comments"][0]["comment"] == comment["comment"]


def test_approve_review_starts_from_final_readiness(review_run):
    with patch("rfp_automation.persistence.checkpoint.load_checkpoint_up_to", return_value={"tracking_rfp_id": review_run}) as mock_load, \
         patch("rfp_automation.api.routes._start_rerun_job") as mock_start:
        response = client.post(
            f"/api/rfp/{review_run}/review/decision",
            json={"decision": "APPROVE", "reviewer": "Alex", "summary": "Looks good."},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["rerun_from"] == "f1_final_readiness"
    mock_load.assert_called_once_with(review_run, "f1_final_readiness")
    mock_start.assert_called_once()
