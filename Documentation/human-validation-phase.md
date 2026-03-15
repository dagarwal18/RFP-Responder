# Human Validation Phase Design

## Goal

Add an asynchronous human validation stage between cluster E and cluster F where a reviewer can:

- browse the full RFP in section order
- inspect the generated response by section
- add comments at section, paragraph, or line level
- approve the package to continue
- request changes and send the run back to the earliest agent that can address those comments

The target user experience is closer to an implementation-plan review workflow than a final yes/no approval button.

## What The Repo Already Supports

- A1 already parses the RFP into structured blocks and semantic chunks with `block_id`, `chunk_index`, `section_hint`, and page ranges.
- Full chunk text is persisted outside Pinecone in `SectionStore`, so the source RFP can be reconstructed for review.
- C2 already produces section-level response objects and requirement coverage data.
- C3 already produces the assembled proposal and section order.
- D1 already produces retry feedback for rewrite loops.
- E1 and E2 are implemented and already sit before the current F-stage.
- Checkpoints and reruns already exist, so we do not need a brand-new resume mechanism.

## Current Gaps

The current system is not yet able to support the review flow you described because:

1. The only human gate is a shallow `/approve` endpoint that flips run status to `SUBMITTED` or `REJECTED`.
2. The graph still assumes F1 is a simple approval gate, not an asynchronous pause with threaded comments.
3. The frontend only renders read-only previews of C2/C3 outputs and does not expose a review workspace.
4. Source-document persistence stops at chunk level, so true line comments are not yet stable.
5. There is no structured comment model that maps reviewer feedback back to a rerun target.

## Recommended Insertion Point

Add a new stage between `commercial_legal_parallel` and `f1_final_readiness`:

- `h1_human_validation_prepare`

Recommended flow:

`D1 -> commercial_legal_parallel -> H1 -> WAIT_FOR_REVIEW`

Then:

- `APPROVE -> f1_final_readiness -> f2_submission`
- `REQUEST_CHANGES -> rerun from selected agent checkpoint`
- `REJECT -> terminal end_rejected`

This is better than overloading the current `/approve` endpoint because your review step is not just a binary approval. It is a pause/resume workflow with comments and targeted reruns.

## Why Checkpoint Resume Is The Right Fit

Your repo already has the exact primitive needed for a human-in-the-loop stage:

- per-agent checkpoints
- rerun from any later agent
- WebSocket progress updates

So the human validation phase should be implemented as:

1. pipeline runs through E
2. H1 builds a review package and sets status to a waiting state
3. graph stops
4. frontend shows the review package
5. user approves or requests changes
6. backend stores comments and either:
   - resumes from `f1_final_readiness` or `f2_submission`
   - reruns from `c1_architecture_planning`, `c2_requirement_writing`, `c3_narrative_assembly`, `d1_technical_validation`, or `commercial_legal_parallel`

This is the closest match to the anti-gravity style review flow you referenced.

## Data Model Changes

### 1. New Pipeline Statuses

Add statuses such as:

- `HUMAN_VALIDATION_PREP`
- `AWAITING_HUMAN_VALIDATION`
- `HUMAN_VALIDATION_REVISION`
- `HUMAN_VALIDATED`

You already have `AWAITING_APPROVAL`, but the new stage needs richer semantics than a final approval toggle.

### 2. Review Package Models

Add new schemas in `models/schemas.py`.

Suggested models:

```python
class ReviewAnchor(BaseModel):
    anchor_id: str
    target_type: str
    target_id: str = ""
    section_id: str = ""
    chunk_id: str = ""
    block_id: str = ""
    paragraph_index: int | None = None
    line_index: int | None = None
    page_number: int | None = None
    text: str = ""


class ReviewComment(BaseModel):
    comment_id: str
    anchor: ReviewAnchor
    source_domain: str
    rerun_hint: str = ""
    severity: str = "medium"
    status: str = "open"
    author: str = ""
    comment: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewDecision(BaseModel):
    decision: str | None = None
    reviewer: str = ""
    summary: str = ""
    rerun_from: str = ""


class ReviewPackage(BaseModel):
    review_id: str = ""
    status: str = "PENDING"
    rfp_sections: list[dict[str, Any]] = []
    response_sections: list[dict[str, Any]] = []
    coverage_matrix: list[CoverageEntry] = []
    comments: list[ReviewComment] = []
    decision: ReviewDecision = Field(default_factory=ReviewDecision)
```

### 3. Graph State

Add fields to `RFPGraphState`:

- `review_package`
- `review_history`
- `selected_rerun_from`

This keeps review state checkpointable and visible through `/status`.

## Source Anchoring Strategy

### MVP

For the first version:

- allow section-level comments on the response
- allow paragraph-level comments on the response
- allow chunk-level comments on the source RFP

This can be built with the data you already persist.

### Full Version

For true line-level commenting, extend A1 parsing to persist:

- `block_id`
- per-block line list
- stable `line_id`
- page number per line

Today `parse_pdf_blocks()` captures line text during parsing but only stores merged block text. That is enough to reconstruct sections, but not enough to support stable line comments across reruns.

Recommended extension:

- keep `blocks` in A1 as first-class persisted review artifacts
- add `lines` under each block
- store them in a new review/source store or extend `SectionStore`

## Response Anchoring Strategy

C2 currently stores only:

- `section_id`
- `title`
- `content`
- `requirements_addressed`

That is enough for section review, but not for stable paragraph or line anchors.

Recommended approach:

- generate paragraph anchors in H1 by splitting `SectionResponse.content`
- assign deterministic IDs like `SEC-003:P2`
- optionally derive line anchors from paragraph wrapping or newline boundaries

This lets you ship paragraph comments quickly without forcing C2 to emit a brand-new structure on day one.

## Routing Reviewer Comments Back To Agents

Each comment should carry a `rerun_hint`, but the backend should also compute an earliest rerun target from all open comments.

Suggested mapping:

- architecture or section placement issue -> `c1_architecture_planning`
- missing or weak generated content -> `c2_requirement_writing`
- narrative flow or document assembly issue -> `c3_narrative_assembly`
- validation disagreement requiring another pass -> `d1_technical_validation`
- pricing or commercial request -> `commercial_legal_parallel`
- legal concern -> `commercial_legal_parallel`
- missed source requirement extraction -> `b1_requirements_extraction`
- validation classification issue -> `b2_requirements_validation`

Rule:

- choose the earliest required agent across all unresolved comments

That keeps the rerun deterministic and compatible with the existing checkpoint system.

## Backend Changes

### 1. New Agent

Add `human_validation_agent.py`.

Responsibilities:

- build the review package from:
  - `structuring_result`
  - persisted source chunks
  - `writing_result.section_responses`
  - `assembled_proposal`
  - `technical_validation`
  - `commercial_result`
  - `legal_result`
- set `state.review_package`
- set status to `AWAITING_HUMAN_VALIDATION`

This agent should not call the LLM by default. It is an orchestration and packaging step.

### 2. Graph Changes

Update `orchestration/graph.py` and `transitions.py` so that:

- `commercial_legal_parallel -> h1_human_validation_prepare`
- `h1_human_validation_prepare -> end_waiting_for_review`
- a resume action can continue from `f1_final_readiness` or a selected earlier node

Do not keep the current direct `commercial_legal_parallel -> f1_final_readiness` path.

### 3. API Changes

Replace the current single `/approve` pattern with review-oriented endpoints.

Recommended endpoints:

- `GET /api/rfp/{rfp_id}/review-package`
- `POST /api/rfp/{rfp_id}/review-comments`
- `PUT /api/rfp/{rfp_id}/review-comments/{comment_id}`
- `DELETE /api/rfp/{rfp_id}/review-comments/{comment_id}`
- `POST /api/rfp/{rfp_id}/review-decision`

`review-decision` request should support:

- `APPROVE`
- `REQUEST_CHANGES`
- `REJECT`

For `REQUEST_CHANGES`, the backend should:

- persist comments
- compute earliest rerun target
- trigger rerun automatically

For `APPROVE`, the backend should:

- persist decision
- rerun from `f1_final_readiness` or `f2_submission`

### 4. Status Endpoint

Extend `/status` so it returns:

- review package metadata
- review decision
- comment counts
- whether the run is waiting on user input

This avoids building the frontend from raw `result` blobs.

## Frontend Changes

### 1. Add A Dedicated Review Workspace

Do not treat this as another small card inside the current agent-output panel.

Recommended layout:

- left rail: RFP section outline
- center pane: source RFP section content
- right pane: generated response section content
- far-right drawer or bottom panel: comments for selected anchor

### 2. Anchor Interaction

On click:

- section header -> create section comment
- paragraph block -> create paragraph comment
- line row -> create line comment

Suggested comment composer fields:

- comment text
- severity
- send back to:
  - auto
  - C1
  - C2
  - C3
  - D1
  - E

### 3. Review UX

At the top of the workspace:

- `Approve and Continue`
- `Request Changes`
- `Reject`

And summary chips:

- open comments
- source comments
- response comments
- earliest rerun target

### 4. Current Frontend Constraint

`frontend/index.html` is already a large single-file dashboard. This review workspace is substantial enough that it will be cleaner if you split the JavaScript into smaller modules or, at minimum, isolate review rendering functions into a dedicated section.

## Suggested Implementation Order

### Phase 1: Working Review Loop

- add statuses, schemas, and state fields
- add H1 review-package agent
- add terminal waiting state after H1
- add review package and decision endpoints
- add frontend review workspace with section and paragraph comments
- on request changes, rerun from computed earliest agent

This gets you the anti-gravity style flow quickly.

### Phase 2: Better Source Anchors

- persist block-level review artifacts from A1
- expose source section tree and page mapping
- support chunk and block comments on the original RFP

### Phase 3: True Line Comments

- persist line-level anchors from A1 parsing
- render lines in the frontend with stable IDs
- allow line-specific comments and carry them through reruns

### Phase 4: Smarter Revision Targeting

- auto-classify comments into rerun targets
- allow selective section rewrite prompts using only affected comments
- preserve comment history across reruns

## Recommended MVP Scope

If you want the fastest useful version, build this first:

- new H1 review-package stage after E
- waiting state and review package endpoint
- frontend side-by-side review of:
  - source RFP chunks by section
  - C2 response sections
- section and paragraph comments
- `REQUEST_CHANGES` rerun to:
  - `c2_requirement_writing`
  - `c3_narrative_assembly`
  - `commercial_legal_parallel`
- `APPROVE` continues to F

That delivers the core human validation behavior without first solving perfect line anchoring.

## Repo-Specific Conclusion

The cleanest design for this repo is not a synchronous in-graph pause. It is:

- package review data after E
- stop in an awaiting-review status
- store reviewer comments structurally
- use existing checkpoint reruns to continue or revise

The backend foundation is already strong enough for this. The two real missing pieces are:

- a structured review package and comment model
- a frontend review workspace instead of the current read-only output viewer
