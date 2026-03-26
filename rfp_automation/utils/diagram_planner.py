"""
Diagram planning helpers for section-aware Mermaid generation.

This module keeps Mermaid creation out of the prose-writing prompt. It selects
diagram types from section intent, extracts section-specific entities and steps,
builds styled Mermaid blocks, and prevents repeated visuals across the document.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

logger = logging.getLogger(__name__)

_FORBIDDEN_SECTION_TOKENS = (
    "cover letter",
    "executive summary",
    "table of contents",
    "pricing",
    "commercial",
    "appendix",
    "declaration",
    "forms",
    "legal",
    "contract",
    "terms",
    "compliance matrix",
    "submission form",
    "company profile",
    "case studies",
    "client references",
    "credentials",
)

_MANDATED_VISUAL_TOKENS = (
    "diagram",
    "visual",
    "chart",
    "topology",
    "workflow",
    "timeline",
    "gantt",
)

_STOP_PHRASES = {
    "Technical",
    "Implementation",
    "Overview",
    "Response",
    "Requirement",
    "Requirements",
    "Solution",
    "Proposal",
    "Client",
    "Service",
    "Services",
}

_LOW_SIGNAL_PHRASES = (
    "one of our",
    "another example",
    "for example",
    "case studies",
    "client references",
    "our experience",
    "our credentials",
    "in one of",
)

_LOW_SIGNAL_WORDS = {
    "a",
    "an",
    "and",
    "another",
    "case",
    "demonstrating",
    "example",
    "for",
    "in",
    "of",
    "one",
    "our",
    "studies",
    "the",
}

_KEYWORD_ENTITY_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("branch", "site", "store", "location"), "Branch Sites"),
    (("user", "employee", "customer", "agent", "operator"), "End Users"),
    (("device", "endpoint", "router", "gateway", "handset"), "Managed Devices"),
    (("edge", "cpe", "sd-wan", "wan"), "Edge Gateway"),
    (("identity", "sso", "iam", "directory"), "Identity Services"),
    (("portal", "application", "app"), "Application Services"),
    (("api", "integration", "middleware", "orchestration"), "Integration Layer"),
    (("workflow", "case", "ticket"), "Workflow Engine"),
    (("platform", "core"), "Core Platform"),
    (("database", "lake", "warehouse", "repository", "data platform"), "Data Services"),
    (("monitor", "observability", "reporting", "analytics"), "Monitoring and Reporting"),
    (("security", "soc", "siem", "threat"), "Security Operations"),
    (("service desk", "itsm", "incident"), "Service Desk"),
    (("cloud",), "Cloud Services"),
    (("azure",), "Azure Services"),
    (("aws",), "AWS Services"),
    (("gcp", "google cloud"), "GCP Services"),
    (("datacenter", "data centre", "data center", "dc"), "Primary Data Centre"),
)

_DEFAULT_PHASES = [
    "Mobilize",
    "Design",
    "Build",
    "Pilot",
    "Rollout",
    "Handover",
]

_DEFAULT_JOURNEY = [
    "Assess scope",
    "Define solution",
    "Deploy changes",
    "Operate service",
]

_DEFAULT_STATES = [
    "Intake",
    "Validate",
    "Design",
    "Execute",
    "Close",
]

_DEFAULT_MESSAGES = [
    "Submit request",
    "Validate policy",
    "Orchestrate action",
    "Return status",
]

_STATE_KEYWORDS = (
    "assess",
    "analysis",
    "analyze",
    "approve",
    "build",
    "close",
    "closure",
    "contain",
    "deploy",
    "design",
    "execute",
    "handover",
    "intake",
    "investigate",
    "mobilize",
    "monitor",
    "operate",
    "plan",
    "qualif",
    "recover",
    "remed",
    "resolve",
    "review",
    "rollout",
    "triage",
    "validate",
    "verification",
)

_PROCESS_KEYWORDS = _STATE_KEYWORDS + (
    "confirm",
    "configure",
    "define",
    "deliver",
    "discover",
    "enable",
    "migrate",
    "prepare",
    "return",
    "stabilize",
    "submit",
    "transition",
)

_TIMELINE_KEYWORDS = (
    "cutover",
    "delivery plan",
    "deployment plan",
    "gantt",
    "go-live",
    "handover plan",
    "implementation plan",
    "implementation roadmap",
    "implementation schedule",
    "migration plan",
    "milestone",
    "mobilization",
    "phase ",
    "phased",
    "pilot",
    "project management",
    "project plan",
    "rollout",
    "schedule",
    "timeline",
    "transition plan",
    "wave ",
)

_MIN_DISTINCT_DIAGRAM_TYPES = 4

_MERMAID_INIT = (
    "%%{init: {'theme': 'base', 'themeVariables': {"
    "'primaryColor': '#EAF2FF', "
    "'primaryTextColor': '#102A43', "
    "'primaryBorderColor': '#1E4E8C', "
    "'lineColor': '#355C7D', "
    "'secondaryColor': '#DFF3EC', "
    "'tertiaryColor': '#FFF1DA', "
    "'mainBkg': '#FFFFFF', "
    "'secondaryTextColor': '#102A43', "
    "'tertiaryTextColor': '#102A43', "
    "'clusterBkg': '#F8FBFF', "
    "'clusterBorder': '#1E4E8C', "
    "'defaultLinkColor': '#355C7D', "
    "'titleColor': '#102A43', "
    "'edgeLabelBackground': '#FFFFFF', "
    "'actorBkg': '#EAF2FF', "
    "'actorBorder': '#1E4E8C', "
    "'actorTextColor': '#102A43', "
    "'actorLineColor': '#355C7D', "
    "'signalColor': '#1E4E8C', "
    "'signalTextColor': '#102A43', "
    "'labelBoxBkgColor': '#FFF1DA', "
    "'labelBoxBorderColor': '#B45309', "
    "'labelTextColor': '#102A43', "
    "'noteBkgColor': '#FFF4DE', "
    "'noteBorderColor': '#B45309', "
    "'noteTextColor': '#102A43', "
    "'sectionBkgColor': '#EAF2FF', "
    "'altSectionBkgColor': '#E8FFF4', "
    "'taskBorderColor': '#1E4E8C', "
    "'taskBkgColor': '#EAF2FF', "
    "'taskTextColor': '#102A43', "
    "'activeTaskBkgColor': '#DFF3EC', "
    "'activeTaskBorderColor': '#0F766E', "
    "'doneTaskBkgColor': '#FFF1DA', "
    "'doneTaskBorderColor': '#B45309', "
    "'gridColor': '#C7D2E3', "
    "'fontFamily': 'Arial', "
    "'fontSize': '15px'"
    "}}}%%"
)


@dataclass
class DiagramRegistry:
    seen_signatures: set[str] = field(default_factory=set)
    seen_contexts: set[str] = field(default_factory=set)
    type_counts: Counter[str] = field(default_factory=Counter)

    def register(self, diagram_type: str, mermaid: str) -> bool:
        signature = _diagram_signature(diagram_type, mermaid)
        if signature in self.seen_signatures:
            return False
        self.seen_signatures.add(signature)
        self.type_counts[diagram_type] += 1
        return True


def build_diagram_block(
    *,
    section_title: str,
    section_description: str = "",
    content_guidance: str = "",
    content: str,
    visual_relevance: str = "auto",
    visual_type_hint: str = "",
    visual_notes: str = "",
    visual_source_terms: Iterable[str] | None = None,
    parent_title: str = "",
    registry: DiagramRegistry | None = None,
) -> str:
    """Return a Mermaid block for this section or an empty string."""
    registry = registry or DiagramRegistry()
    context_signature = _context_signature(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_type_hint=visual_type_hint,
    )
    if context_signature in registry.seen_contexts:
        return ""
    if not _should_render_diagram(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_relevance=visual_relevance,
    ):
        return ""

    candidate_types = _diagram_candidates(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_type_hint=visual_type_hint,
        visual_relevance=visual_relevance,
        parent_title=parent_title,
    )
    if not candidate_types:
        return ""
    candidate_types = _prioritize_candidate_types(candidate_types, registry)

    for diagram_type in candidate_types:
        mermaid = _build_diagram_mermaid(
            diagram_type=diagram_type,
            section_title=section_title,
            section_description=section_description,
            content_guidance=content_guidance,
            content=content,
            visual_notes=visual_notes,
            visual_source_terms=list(visual_source_terms or []),
            parent_title=parent_title,
        )
        if not mermaid:
            continue
        if not registry.register(diagram_type, mermaid):
            continue
        registry.seen_contexts.add(context_signature)
        return f"```mermaid\n{mermaid}\n```"

    logger.debug("[DiagramPlanner] Skipped duplicated or invalid visual for %s", section_title)
    return ""


def _should_render_diagram(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_relevance: str,
) -> bool:
    lowered_title = (section_title or "").lower()
    if any(token in lowered_title for token in _FORBIDDEN_SECTION_TOKENS):
        return False

    if visual_relevance == "none":
        return False
    if visual_relevance == "required":
        return True

    context = " ".join(
        part.lower()
        for part in (section_title, section_description, content_guidance, content)
        if part
    )
    if any(token in context for token in _MANDATED_VISUAL_TOKENS):
        return True

    semantic_tokens = (
        "architecture",
        "topology",
        "integration",
        "workflow",
        "process",
        "lifecycle",
        "migration",
        "rollout",
        "timeline",
        "project management",
        "implementation plan",
        "operations",
        "support model",
        "service model",
        "operating model",
        "data flow",
        "security workflow",
    )
    return any(token in context for token in semantic_tokens) or _looks_like_gantt_section(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
    )


def _diagram_candidates(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_type_hint: str,
    visual_relevance: str,
    parent_title: str,
) -> list[str]:
    lowered = " ".join(
        part.lower()
        for part in (parent_title, section_title, section_description, content_guidance, content)
        if part
    )
    hint = (visual_type_hint or "").lower().strip()

    if hint in {"gantt", "sequence", "state", "journey", "class", "er"}:
        return [_normalize_hint_to_type(hint)]
    if hint == "architecture":
        return ["flowchart", "sequenceDiagram", "classDiagram"]

    if _looks_like_gantt_section(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        parent_title=parent_title,
    ):
        return ["gantt"]
    if any(token in lowered for token in ("data model", "data architecture", "entity", "schema", "repository", "master data", "data domain", "record model")):
        return ["erDiagram", "classDiagram", "flowchart"]
    if any(token in lowered for token in ("interconnect", "integration", "interface", "api", "handoff", "synchronization", "data exchange")):
        return ["sequenceDiagram", "flowchart", "stateDiagram-v2"]
    if any(token in lowered for token in ("governance", "roles and responsibilities", "responsibility", "ownership", "support matrix", "escalation matrix")):
        return ["journey", "stateDiagram-v2", "sequenceDiagram"]
    if any(token in lowered for token in ("lifecycle", "incident", "escalation", "triage", "operations workflow", "state transition")):
        return ["stateDiagram-v2", "journey", "sequenceDiagram"]
    if any(token in lowered for token in ("process", "workflow", "operating model", "service model", "onboarding", "support model")):
        return ["journey", "stateDiagram-v2", "flowchart", "sequenceDiagram"]
    if any(token in lowered for token in ("component", "module", "service decomposition", "platform component")):
        return ["classDiagram", "flowchart", "erDiagram"]
    if any(token in lowered for token in ("architecture", "topology", "deployment", "network", "platform", "technical solution")):
        return ["flowchart", "sequenceDiagram", "classDiagram", "stateDiagram-v2"]
    if visual_relevance == "required":
        return ["flowchart", "sequenceDiagram", "journey", "stateDiagram-v2"]
    return []


def _normalize_hint_to_type(hint: str) -> str:
    return {
        "sequence": "sequenceDiagram",
        "state": "stateDiagram-v2",
        "journey": "journey",
        "class": "classDiagram",
        "gantt": "gantt",
        "er": "erDiagram",
    }.get(hint, "flowchart")


def _prioritize_candidate_types(candidate_types: list[str], registry: DiagramRegistry) -> list[str]:
    deduped = list(dict.fromkeys(candidate_types))
    if len(deduped) <= 1:
        return deduped

    if "gantt" in deduped and registry.type_counts["gantt"] == 0:
        others = [diagram_type for diagram_type in deduped if diagram_type != "gantt"]
        return ["gantt", *others]

    if len(registry.type_counts) < _MIN_DISTINCT_DIAGRAM_TYPES:
        unseen = [diagram_type for diagram_type in deduped if registry.type_counts[diagram_type] == 0]
        seen = [diagram_type for diagram_type in deduped if registry.type_counts[diagram_type] > 0]
        if unseen:
            return unseen + sorted(
                seen,
                key=lambda diagram_type: (registry.type_counts[diagram_type], deduped.index(diagram_type)),
            )

    return sorted(
        deduped,
        key=lambda diagram_type: (registry.type_counts[diagram_type], deduped.index(diagram_type)),
    )


def _build_diagram_mermaid(
    *,
    diagram_type: str,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_notes: str,
    visual_source_terms: list[str],
    parent_title: str,
) -> str:
    if diagram_type == "gantt":
        return _build_gantt(
            section_description=section_description,
            content_guidance=content_guidance,
            content=content,
            visual_notes=visual_notes,
        )
    if diagram_type == "sequenceDiagram":
        return _build_sequence(
            section_title=section_title,
            section_description=section_description,
            content_guidance=content_guidance,
            content=content,
            visual_notes=visual_notes,
            visual_source_terms=visual_source_terms,
        )
    if diagram_type == "stateDiagram-v2":
        return _build_state_diagram(
            section_description=section_description,
            content_guidance=content_guidance,
            content=content,
        )
    if diagram_type == "journey":
        return _build_journey(
            section_title=section_title,
            section_description=section_description,
            content_guidance=content_guidance,
            content=content,
        )
    if diagram_type == "classDiagram":
        return _build_class_diagram(
            section_description=section_description,
            content_guidance=content_guidance,
            content=content,
            visual_source_terms=visual_source_terms,
        )
    if diagram_type == "erDiagram":
        return _build_er_diagram(
            section_description=section_description,
            content_guidance=content_guidance,
            content=content,
            visual_source_terms=visual_source_terms,
        )
    return _build_architecture_flow(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_notes=visual_notes,
        visual_source_terms=visual_source_terms,
        parent_title=parent_title,
    )


def _looks_like_gantt_section(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    parent_title: str = "",
) -> bool:
    title_context = " ".join(
        part.lower()
        for part in (parent_title, section_title, section_description, content_guidance)
        if part
    )
    if any(token in title_context for token in _TIMELINE_KEYWORDS):
        return True

    lowered_content = (content or "").lower()
    phase_markers = re.findall(r"\b(?:phase|wave|milestone)\s+\d+\b", lowered_content)
    delivery_tokens = (
        "mobilize",
        "design",
        "build",
        "pilot",
        "rollout",
        "cutover",
        "handover",
        "transition",
        "deploy",
        "stabilize",
        "go-live",
    )
    delivery_hits = sum(1 for token in delivery_tokens if token in lowered_content)
    return len(phase_markers) >= 1 or delivery_hits >= 3


def _build_architecture_flow(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_notes: str,
    visual_source_terms: list[str],
    parent_title: str,
) -> str:
    labels = _extract_entities(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_notes=visual_notes,
        visual_source_terms=visual_source_terms,
        limit=5,
    )
    if len(labels) < 4:
        labels.extend(
            label
            for label in ["User Channels", "Access Layer", "Core Platform", "Assurance Services"]
            if label not in labels
        )
    labels = labels[:5]

    node_ids = [f"N{idx}" for idx in range(1, len(labels) + 1)]
    classes = ["edge", "edge", "core", "core", "ops", "ops"]
    lines = [
        _MERMAID_INIT,
        "flowchart LR",
        "    classDef edge fill:#EAF2FF,stroke:#1E4E8C,color:#102A43,stroke-width:2px;",
        "    classDef core fill:#E8FFF4,stroke:#0F766E,color:#102A43,stroke-width:2px;",
        "    classDef ops fill:#FFF4DE,stroke:#B45309,color:#102A43,stroke-width:2px;",
    ]
    for node_id, label in zip(node_ids, labels):
        lines.append(f'    {node_id}["{_wrap_flow_label(label)}"]')
    for left, right in zip(node_ids, node_ids[1:]):
        lines.append(f"    {left} --> {right}")
    if len(node_ids) >= 4:
        lines.append(f"    {node_ids[1]} -. telemetry .-> {node_ids[-1]}")
    for node_id, css_class in zip(node_ids, classes):
        lines.append(f"    class {node_id} {css_class};")
    return "\n".join(lines)


def _build_sequence(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_notes: str,
    visual_source_terms: list[str],
) -> str:
    participants = _extract_entities(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_notes=visual_notes,
        visual_source_terms=visual_source_terms,
        limit=4,
    )
    if len(participants) < 3:
        participants.extend(
            label
            for label in ["Request Channel", "Integration Layer", "Target Platform", "Operations Team"]
            if label not in participants
        )
    participants = participants[:4]
    actor_ids = [f"P{idx}" for idx in range(1, len(participants) + 1)]
    steps = _extract_process_steps(content, limit=4)
    if len(steps) < 3:
        steps = _DEFAULT_MESSAGES[:]

    lines = [_MERMAID_INIT, "sequenceDiagram", "    autonumber"]
    for actor_id, label in zip(actor_ids, participants):
        lines.append(f"    participant {actor_id} as {_compact_label(label, max_words=3, max_chars=22)}")

    for idx, step in enumerate(steps):
        left = actor_ids[idx % (len(actor_ids) - 1)]
        right = actor_ids[min((idx % (len(actor_ids) - 1)) + 1, len(actor_ids) - 1)]
        lines.append(f"    {left}->>{right}: {_compact_label(step, max_words=4, max_chars=36)}")
    lines.append(f"    {actor_ids[-1]}-->>{actor_ids[0]}: Confirm status and next action")
    return "\n".join(lines)


def _build_gantt(
    *,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_notes: str,
) -> str:
    phases = _extract_steps(content, limit=5)
    if len(phases) < 4:
        phases = _extract_steps(" ".join([content_guidance, section_description, content]), limit=5)
    if len(phases) < 4:
        phases = _DEFAULT_PHASES[:]

    durations = [10, 12, 15, 18, 20, 8]
    start_date = date.today()
    lines = [
        _MERMAID_INIT,
        "gantt",
        "    title Implementation Timeline",
        "    dateFormat YYYY-MM-DD",
        "    axisFormat %d %b",
        "    section Delivery",
    ]
    for idx, phase in enumerate(phases[:5], start=1):
        start_ref = start_date.isoformat() if idx == 1 else f"after phase_{idx - 1}"
        duration = f"{durations[idx - 1]}d"
        tags = "done" if idx == 1 else "active" if idx == 2 else ""
        tag_prefix = f"{tags}, " if tags else ""
        lines.append(
            f"    {_compact_label(phase, max_words=4, max_chars=40)} : "
            f"{tag_prefix}phase_{idx}, {start_ref}, {duration}"
        )
        start_date = start_date + timedelta(days=durations[idx - 1])
    if visual_notes:
        lines.append("    section Governance")
        lines.append("    Steering checkpoint : milestone, gate_1, after phase_2, 0d")
    return "\n".join(lines)


def _build_state_diagram(
    *,
    section_description: str,
    content_guidance: str,
    content: str,
) -> str:
    states = _extract_steps(content, limit=4)
    if len(states) < 4:
        return ""
    if sum(1 for label in states if _is_state_like_label(label)) < 3:
        return ""
    state_ids = [_state_label_to_id(label, idx) for idx, label in enumerate(states, start=1)]
    lines = [_MERMAID_INIT, "stateDiagram-v2"]
    for state_id, label in zip(state_ids, states):
        lines.append(f'    state "{_compact_label(label, max_words=4, max_chars=40)}" as {state_id}')
    lines.append("    [*] --> " + state_ids[0])
    for left, right in zip(state_ids, state_ids[1:]):
        lines.append(f"    {left} --> {right}")
    lines.append(f"    {state_ids[-1]} --> [*]")
    return "\n".join(lines)


def _build_journey(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
) -> str:
    steps = _extract_process_steps(content, limit=4)
    if len(steps) < 4:
        steps = _extract_process_steps(
            " ".join([content_guidance, section_description, content]),
            limit=4,
        )
    if len(steps) < 4:
        return ""

    actors = _extract_entities(
        section_title=section_title,
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_notes="",
        visual_source_terms=[],
        limit=2,
    )
    if len(actors) < 2:
        actors = ["Delivery Team", "Client Stakeholders"]

    lines = [_MERMAID_INIT, "journey", f"    title {_compact_label(section_title, max_words=5, max_chars=42)} Journey"]
    section_labels = ["Discover", "Design", "Deploy", "Operate"]
    for idx, step in enumerate(steps[:4]):
        lines.append(f"    section {section_labels[idx]}")
        score = max(3, 5 - idx)
        lines.append(f"      {step}: {score}: {actors[0]}, {actors[1]}")
    return "\n".join(lines)


def _build_class_diagram(
    *,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_source_terms: list[str],
) -> str:
    entities = _extract_entities(
        section_title="",
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_notes="",
        visual_source_terms=visual_source_terms,
        limit=5,
    )
    if len(entities) < 3:
        entities.extend(
            label
            for label in ["Presentation Layer", "Integration Layer", "Core Services", "Data Services"]
            if label not in entities
        )
    entities = entities[:5]
    class_names = [_class_name(label, idx) for idx, label in enumerate(entities, start=1)]

    lines = [_MERMAID_INIT, "classDiagram"]
    for class_name, label in zip(class_names, entities):
        lines.append(f"    class {class_name} {{")
        lines.append(f"        +{_class_field(label)}")
        lines.append("    }")
    for left, right in zip(class_names, class_names[1:]):
        lines.append(f"    {left} --> {right}")
    if len(class_names) >= 4:
        lines.append(f"    {class_names[1]} ..> {class_names[-1]}")
    return "\n".join(lines)


def _build_er_diagram(
    *,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_source_terms: list[str],
) -> str:
    entities = _extract_entities(
        section_title="",
        section_description=section_description,
        content_guidance=content_guidance,
        content=content,
        visual_notes="",
        visual_source_terms=visual_source_terms,
        limit=4,
    )
    if len(entities) < 3:
        entities.extend(
            label
            for label in ["Request Data", "Integration Layer", "Core Records", "Reporting Data"]
            if label not in entities
        )
    entities = entities[:4]
    entity_names = [_er_name(label, idx) for idx, label in enumerate(entities, start=1)]

    lines = [_MERMAID_INIT, "erDiagram"]
    for entity_name, label in zip(entity_names, entities):
        lines.append(f"    {entity_name} {{")
        lines.append(f"        string {_class_field(label)}")
        lines.append("    }")
    for left, right in zip(entity_names, entity_names[1:]):
        lines.append(f"    {left} ||--o{{ {right} : feeds")
    return "\n".join(lines)


def _extract_entities(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_notes: str,
    visual_source_terms: list[str],
    limit: int,
) -> list[str]:
    source = " ".join(
        part
        for part in (
            section_description,
            content_guidance,
            visual_notes,
            " ".join(visual_source_terms),
            content,
        )
        if part
    )
    entities: list[str] = []
    seen: set[str] = set()

    def _add(label: str) -> None:
        compact = _compact_label(label, max_words=4, max_chars=28)
        key = compact.lower()
        if not compact or key in seen or _is_low_signal_label(compact):
            return
        seen.add(key)
        entities.append(compact)

    for term in visual_source_terms:
        _add(term)

    capitalized = re.findall(
        r"\b(?:[A-Z][A-Za-z0-9+./-]+(?:\s+[A-Z][A-Za-z0-9+./-]+){0,2}|[A-Z]{2,}(?:[-/][A-Z0-9]{2,})*)\b",
        source,
    )
    for phrase in capitalized:
        if phrase in _STOP_PHRASES:
            continue
        _add(phrase)
        if len(entities) >= limit:
            return entities[:limit]

    lowered = source.lower()
    for keywords, label in _KEYWORD_ENTITY_MAP:
        if any(keyword in lowered for keyword in keywords):
            _add(label)
        if len(entities) >= limit:
            return entities[:limit]

    title_tokens = [token.title() for token in re.findall(r"[A-Za-z]{4,}", section_title or "")[:4]]
    for token in title_tokens:
        _add(token)
        if len(entities) >= limit:
            return entities[:limit]
    return entities[:limit]


def _extract_steps(text: str, limit: int) -> list[str]:
    if not text:
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        stripped = re.sub(r"^[\-\*\d\.\)\( ]+", "", raw_line.strip())
        stripped = re.sub(r"^(?:phase|step|milestone|workstream)\s*\d+\s*[:\-]?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = stripped.split("|", 1)[0].strip()
        if len(stripped.split()) < 2:
            continue
        label = _compact_label(stripped, max_words=4, max_chars=36)
        key = label.lower()
        if not label or key in seen or _is_low_signal_label(label):
            continue
        seen.add(key)
        candidates.append(label)
        if len(candidates) == limit:
            return candidates

    if "\n" in text and len(candidates) >= min(limit, 3):
        return candidates[:limit]

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        label = _compact_label(sentence, max_words=4, max_chars=36)
        key = label.lower()
        if not label or key in seen or _is_low_signal_label(label):
            continue
        seen.add(key)
        candidates.append(label)
        if len(candidates) == limit:
            break
    return candidates[:limit]


def _extract_process_steps(text: str, limit: int) -> list[str]:
    valid_steps: list[str] = []
    for label in _extract_steps(text, limit=max(limit * 2, limit)):
        if not _is_process_like_label(label):
            continue
        valid_steps.append(label)
        if len(valid_steps) == limit:
            break
    return valid_steps


def _compact_label(text: str, max_words: int = 4, max_chars: int = 32) -> str:
    cleaned = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text or "")
    cleaned = re.sub(r"[`*_#>\[\]{}()]", " ", cleaned)
    cleaned = re.sub(r"^(?:our|your|their)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:one|another)\s+of\s+(?:our|the)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,:;")
    if not cleaned:
        return ""
    words = cleaned.split()
    compact_words: list[str] = []
    for word in words[:max_words]:
        candidate = " ".join(compact_words + [word]).strip(" -,:;")
        if compact_words and len(candidate) > max_chars:
            break
        if not compact_words and len(candidate) > max_chars:
            return candidate[:max_chars].rstrip(" -,:;")
        compact_words.append(word)
    compact = " ".join(compact_words).strip(" -,:;")
    return compact or cleaned[:max_chars].rstrip(" -,:;")


def _diagram_signature(diagram_type: str, mermaid: str) -> str:
    normalized: list[str] = []
    for line in mermaid.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%{") or stripped.startswith("title "):
            continue
        if stripped.startswith(("classDef", "class ", "style ", "linkStyle")):
            continue
        normalized.append(stripped.lower())
    digest = hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()
    return f"{diagram_type}:{digest}"


def _context_signature(
    *,
    section_title: str,
    section_description: str,
    content_guidance: str,
    content: str,
    visual_type_hint: str,
) -> str:
    normalized = "\n".join(
        part.strip().lower()
        for part in (
            section_title,
            section_description,
            content_guidance,
            content,
            visual_type_hint,
        )
        if part and part.strip()
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _state_label_to_id(label: str, index: int) -> str:
    words = re.findall(r"[A-Za-z0-9]+", label)
    if not words:
        return f"Stage{index}"
    return "".join(word.title() for word in words[:3]) or f"Stage{index}"


def _is_low_signal_label(label: str) -> bool:
    lowered = (label or "").lower().strip()
    if not lowered:
        return True
    if any(phrase in lowered for phrase in _LOW_SIGNAL_PHRASES):
        return True
    words = re.findall(r"[a-z0-9]+", lowered)
    meaningful = [word for word in words if word not in _LOW_SIGNAL_WORDS]
    return len(meaningful) < 2


def _is_state_like_label(label: str) -> bool:
    lowered = (label or "").lower().strip()
    if not lowered:
        return False
    if any(token in lowered for token in (" is ", " are ", " will ", " should ", " must ", " to ensure ")):
        return False
    if any(char in lowered for char in ":;,.><=%"):
        return False
    words = re.findall(r"[a-z0-9]+", lowered)
    if len(words) < 2 or len(words) > 4:
        return False
    return any(keyword in lowered for keyword in _STATE_KEYWORDS)


def _is_process_like_label(label: str) -> bool:
    lowered = (label or "").lower().strip()
    if not lowered:
        return False
    if any(token in lowered for token in (" is ", " are ", " will ", " should ", " must ", " to ensure ")):
        return False
    if any(char in lowered for char in ":;,.><=%"):
        return False
    words = re.findall(r"[a-z0-9]+", lowered)
    if len(words) < 2 or len(words) > 5:
        return False
    return any(keyword in lowered for keyword in _PROCESS_KEYWORDS)


def _wrap_flow_label(label: str) -> str:
    words = label.split()
    if len(words) <= 2:
        return label
    midpoint = min(2, len(words) - 1)
    return "<br/>".join([" ".join(words[:midpoint]), " ".join(words[midpoint:])])


def _er_name(label: str, index: int) -> str:
    words = re.findall(r"[A-Za-z0-9]+", label)
    if not words:
        return f"Entity_{index}"
    return "_".join(word.title() for word in words[:3])


def _class_name(label: str, index: int) -> str:
    words = re.findall(r"[A-Za-z0-9]+", label)
    name = "".join(word.title() for word in words[:3]) or f"Component{index}"
    if name[0].isdigit():
        name = f"Component{index}{name}"
    return name


def _class_field(label: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", label.lower())
    if not words:
        return "capability"
    return "_".join(words[:2])
