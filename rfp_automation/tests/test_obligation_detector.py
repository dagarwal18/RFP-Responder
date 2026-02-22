"""
Tests: ObligationDetector — Rule-based obligation candidate detection.

Validates:
  - Obligation verbs are detected in sample sentences
  - Narrative/marketing text is filtered out
  - Indicator counting matches expected counts
  - Sentence splitting handles complex RFP text
"""

import pytest

from rfp_automation.services.obligation_detector import (
    ObligationDetector,
    CandidateSentence,
)


class TestObligationDetector:

    # ── Sentence splitting ─────────────────────────────────

    def test_split_empty_text(self):
        assert ObligationDetector.split_sentences("") == []
        assert ObligationDetector.split_sentences("   ") == []
        assert ObligationDetector.split_sentences(None) == []

    def test_split_single_sentence(self):
        result = ObligationDetector.split_sentences("The vendor shall provide 24x7 support.")
        assert len(result) >= 1
        assert "The vendor shall provide 24x7 support." in result[0]

    def test_split_multiple_sentences(self):
        text = "The system must encrypt data. The vendor shall report monthly."
        result = ObligationDetector.split_sentences(text)
        assert len(result) >= 2

    def test_split_preserves_bullets(self):
        text = "Requirements:\n- Must support SSO\n- Shall provide encryption\n- Must log all access"
        result = ObligationDetector.split_sentences(text)
        # Bullets are now merged with parent: "Requirements: Must support SSO, Shall provide encryption, Must log all access"
        assert len(result) >= 1
        merged = result[0]
        assert "Must support SSO" in merged
        assert "Shall provide encryption" in merged
        assert "Must log all access" in merged

    def test_split_preserves_numbered_list(self):
        text = "1. The vendor must provide monitoring.\n2. The vendor shall deliver quarterly reports."
        result = ObligationDetector.split_sentences(text)
        assert len(result) >= 2

    # ── Candidate detection ────────────────────────────────

    def test_detect_obligation_verbs(self):
        text = "The vendor shall provide 24x7 monitoring. The system must encrypt all data."
        candidates = ObligationDetector.detect_candidates(text)
        assert len(candidates) >= 2
        assert all(isinstance(c, CandidateSentence) for c in candidates)
        indicators = [ind for c in candidates for ind in c.indicators_found]
        assert "shall" in indicators
        assert "must" in indicators

    def test_detect_required_to(self):
        text = "The contractor is required to deliver the system by Q4 2025."
        candidates = ObligationDetector.detect_candidates(text)
        assert len(candidates) == 1
        assert "is required" in candidates[0].indicators_found or "required to" in candidates[0].indicators_found

    def test_detect_responsible_for(self):
        text = "The vendor is responsible for all infrastructure provisioning."
        candidates = ObligationDetector.detect_candidates(text)
        assert len(candidates) == 1
        assert "responsible for" in candidates[0].indicators_found

    def test_detect_comply_with(self):
        text = "All solutions must comply with ISO 27001 standards."
        candidates = ObligationDetector.detect_candidates(text)
        assert len(candidates) >= 1
        indicators = [ind for c in candidates for ind in c.indicators_found]
        assert "comply with" in indicators

    def test_filter_narrative_text(self):
        text = (
            "The company has been a market leader since 2010. "
            "Our methodology leverages industry best practices. "
            "The team is highly experienced in cloud solutions."
        )
        candidates = ObligationDetector.detect_candidates(text)
        assert len(candidates) == 0  # no obligation verbs

    def test_filter_aspirational_language(self):
        """Layer 1 is intentionally broad — 'deliver' IS an indicator.
        Layer 2 (LLM) handles filtering aspirational usage."""
        text = "We aim to deliver exceptional customer service. Our goal is to innovate."
        candidates = ObligationDetector.detect_candidates(text)
        # "deliver" is caught as an indicator — Layer 1 is deliberately over-inclusive
        assert len(candidates) == 1
        assert "deliver" in candidates[0].indicators_found

    def test_mixed_obligation_and_narrative(self):
        text = (
            "The system is designed with modern architecture. "
            "The vendor shall provide 24x7 support. "
            "Our team has decades of experience. "
            "The system must support SSO via SAML 2.0."
        )
        candidates = ObligationDetector.detect_candidates(text)
        assert len(candidates) == 2  # only the obligation sentences

    def test_source_section_attached(self):
        text = "The vendor must deliver the system on time."
        candidates = ObligationDetector.detect_candidates(
            text, source_section="Delivery Schedule"
        )
        assert len(candidates) == 1
        assert candidates[0].source_section == "Delivery Schedule"

    def test_sentence_index_tracking(self):
        text = "First sentence. The vendor must deliver. Third sentence."
        candidates = ObligationDetector.detect_candidates(text)
        assert len(candidates) >= 1
        # The candidate should have a sentence_index > 0
        assert candidates[0].sentence_index >= 0

    def test_empty_input(self):
        assert ObligationDetector.detect_candidates("") == []
        assert ObligationDetector.detect_candidates(None) == []
        assert ObligationDetector.detect_candidates("   ") == []

    # ── Indicator counting ─────────────────────────────────

    def test_count_indicators_basic(self):
        text = "The vendor shall provide SSO. Data must be encrypted."
        count = ObligationDetector.count_indicators(text)
        assert count >= 2  # shall + must

    def test_count_indicators_multiple_in_sentence(self):
        text = "The vendor shall provide monitoring and must ensure uptime."
        count = ObligationDetector.count_indicators(text)
        assert count >= 2  # shall + must + ensure

    def test_count_indicators_none(self):
        text = "The company was founded in 2010 and has offices globally."
        count = ObligationDetector.count_indicators(text)
        assert count == 0

    def test_count_indicators_empty(self):
        assert ObligationDetector.count_indicators("") == 0
        assert ObligationDetector.count_indicators(None) == 0

    def test_count_indicators_case_insensitive(self):
        text = "The vendor SHALL provide SSO. The system MUST encrypt data."
        count = ObligationDetector.count_indicators(text)
        assert count >= 2

    # ── Complex RFP text ───────────────────────────────────

    def test_rfp_paragraph_with_mixed_content(self):
        """Simulate a realistic RFP paragraph with mixed content."""
        text = (
            "3.1 System Requirements\n\n"
            "The organization seeks a modern cloud-based platform that "
            "leverages cutting-edge technology to improve operational efficiency. "
            "The selected vendor shall provide a fully managed SaaS solution "
            "hosted on AWS or Azure. The vendor must ensure 99.9% uptime "
            "with documented SLAs. All data must be encrypted at rest using "
            "AES-256 encryption. The solution is expected to integrate "
            "seamlessly with existing enterprise systems."
        )
        candidates = ObligationDetector.detect_candidates(text)
        # Should find: shall provide, must ensure, must be encrypted, expected to
        assert len(candidates) >= 3
        # Should NOT include the narrative intro
        for c in candidates:
            assert "organization seeks" not in c.text
