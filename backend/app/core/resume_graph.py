"""Structured resume memory — §12.1.

Instead of re-sending the full resume text into every LLM call (Stage 2 keyword
matching, Stage 3 per-posting scoring), parse the resume **once** into a
lightweight entity graph and reference it by ID thereafter.

Graph structure:
    - Nodes: skills, roles, projects, tools, metrics, each extracted once
    - Edges: "used_in" (skill → project), "demonstrates" (project → metric),
             "held" (role → date range)

For Stage 3's per-posting loop, pull only the subgraph relevant to that JD's
keywords — this turns O(N × full_resume_tokens) into O(N × relevant_subgraph_tokens).

Implementation is pure Python dicts (no NetworkX dependency needed for v1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResumeNode:
    """A single entity node in the resume graph."""
    id: str
    kind: str          # "skill" | "role" | "project" | "tool" | "metric"
    text: str          # e.g. "Python", "RAG system", "10k requests/day"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResumeEdge:
    """A directed edge between two nodes."""
    source_id: str
    target_id: str
    relation: str      # "used_in" | "demonstrates" | "held" | "related"


@dataclass
class ResumeGraph:
    """The complete structured resume memory."""
    nodes: dict[str, ResumeNode]
    edges: list[ResumeEdge]

    def get_node(self, node_id: str) -> ResumeNode | None:
        return self.nodes.get(node_id)

    def get_edges_from(self, node_id: str) -> list[ResumeEdge]:
        return [e for e in self.edges if e.source_id == node_id]

    def get_edges_to(self, node_id: str) -> list[ResumeEdge]:
        return [e for e in self.edges if e.target_id == node_id]

    def get_neighbors(self, node_id: str) -> dict[str, list[ResumeNode]]:
        """Get all neighbors of a node, grouped by edge relation."""
        neighbors: dict[str, list[ResumeNode]] = {}
        for edge in self.get_edges_from(node_id):
            node = self.nodes.get(edge.target_id)
            if node:
                neighbors.setdefault(edge.relation, []).append(node)
        for edge in self.get_edges_to(node_id):
            node = self.nodes.get(edge.source_id)
            if node:
                neighbors.setdefault(edge.relation, []).append(node)
        return neighbors

    def subgraph_for_keywords(self, keywords: list[str]) -> ResumeGraph:
        """Extract the subgraph relevant to the given JD keywords.

        This is the key token-saver: instead of passing the full resume
        text, pass only the nodes/edges relevant to each JD's keywords.
        """
        matched_node_ids: set[str] = set()

        # Find nodes whose text matches any keyword (case-insensitive)
        lowered_keywords = [k.lower() for k in keywords]
        for node_id, node in self.nodes.items():
            text_lower = node.text.lower()
            for kw in lowered_keywords:
                if kw in text_lower or text_lower in kw:
                    matched_node_ids.add(node_id)
                    break

        # Also include neighbors of matched nodes (1-hop expansion)
        for node_id in list(matched_node_ids):
            for edge in self.get_edges_from(node_id):
                matched_node_ids.add(edge.target_id)
            for edge in self.get_edges_to(node_id):
                matched_node_ids.add(edge.source_id)

        # Build subgraph
        sub_nodes = {nid: self.nodes[nid] for nid in matched_node_ids if nid in self.nodes}
        sub_edges = [
            e for e in self.edges
            if e.source_id in matched_node_ids and e.target_id in matched_node_ids
        ]
        return ResumeGraph(nodes=sub_nodes, edges=sub_edges)

    def to_prompt_context(self) -> str:
        """Serialize the graph as a compact text block for LLM prompts."""
        lines = ["=== Resume Entity Graph ==="]
        for node in self.nodes.values():
            lines.append(f"[{node.kind.upper()}] {node.text}")
            for edge in self.get_edges_from(node.id):
                target = self.nodes.get(edge.target_id)
                if target:
                    lines.append(f"  --[{edge.relation}]--> {target.text}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage."""
        return {
            "nodes": {
                nid: {"kind": n.kind, "text": n.text, "metadata": n.metadata}
                for nid, n in self.nodes.items()
            },
            "edges": [
                {"source": e.source_id, "target": e.target_id, "relation": e.relation}
                for e in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResumeGraph:
        """Deserialize from dict."""
        nodes = {
            nid: ResumeNode(id=nid, kind=v["kind"], text=v["text"], metadata=v.get("metadata", {}))
            for nid, v in data.get("nodes", {}).items()
        }
        edges = [
            ResumeEdge(source_id=e["source"], target_id=e["target"], relation=e["relation"])
            for e in data.get("edges", [])
        ]
        return cls(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Extraction: parse resume text into a ResumeGraph
# ---------------------------------------------------------------------------

# Simple heuristic patterns for entity extraction (no LLM needed)
_SKILL_PATTERNS = [
    re.compile(r"(?:skills|technologies|tech stack)[:\s]*(.*)", re.I),
    re.compile(r"(?:proficient in|experienced with|knowledge of)[:\s]*(.*)", re.I),
]
_ROLE_PATTERNS = [
    re.compile(r"(?:^|\n)\s*(?:senior |lead |staff |principal )?\w+\s+engineer", re.I),
    re.compile(r"(?:^|\n)\s*(?:sr\.?|lead|staff|principal)\s+\w+", re.I),
]
_PROJECT_PATTERNS = [
    re.compile(r"built a (.+?)(?:\.|,|\n)", re.I),
    re.compile(r"developed a (.+?)(?:\.|,|\n)", re.I),
    re.compile(r"shipped a (.+?)(?:\.|,|\n)", re.I),
    re.compile(r"designed and implemented (.+?)(?:\.|,|\n)", re.I),
]
_METRIC_PATTERNS = [
    re.compile(r"(\d+[kKmM]?\s*(?:requests|users|calls|QPS|RPS)[^.\n]*)", re.I),
    re.compile(r"(\d+%?\s*(?:reduction|improvement|increase|accuracy|faster)[^.\n]*)", re.I),
]


def extract_resume_graph(bullets: list[dict[str, str]], skills_raw: str = "") -> ResumeGraph:
    """Heuristic extraction of resume entities into a graph.

    Args:
        bullets: List of dicts with at least {"section": str, "text": str}.
        skills_raw: Raw skills line/paragraph from the resume.
    """
    nodes: dict[str, ResumeNode] = {}
    edges: list[ResumeEdge] = []

    node_counter = 0

    def _add_node(kind: str, text: str, **meta) -> str:
        nonlocal node_counter
        node_counter += 1
        nid = f"{kind}_{node_counter}"
        nodes[nid] = ResumeNode(id=nid, kind=kind, text=text.strip(), metadata=meta)
        return nid

    # Extract skills from the skills section or raw text
    if skills_raw:
        # Split by common delimiters
        raw_skills = re.split(r"[,\n/;|]", skills_raw)
        skill_ids: list[str] = []
        for s in raw_skills:
            s = s.strip()
            if s and len(s) < 60:
                sid = _add_node("skill", s)
                skill_ids.append(sid)

    # Extract from bullets — use the bullet's own ID (e.g. "b0", "b1") as
    # the node ID so subgraph_for_keywords can match against parsed.bullets.
    bullet_ids: list[str] = []
    for bullet in bullets:
        text = bullet.get("text", "")
        if not text.strip():
            continue
        bid = bullet.get("id", f"b{len(bullet_ids)}")
        nodes[bid] = ResumeNode(id=bid, kind="project", text=text.strip(),
                                metadata={"section": bullet.get("section", "")})
        bullet_ids.append(bid)

        # Extract metrics from this bullet
        for pat in _METRIC_PATTERNS:
            m = pat.search(text)
            if m:
                mid = _add_node("metric", m.group(1))
                edges.append(ResumeEdge(source_id=bid, target_id=mid, relation="demonstrates"))

        # Extract skills mentioned in this bullet
        text_lower = text.lower()
        for sid in skill_ids:
            skill_node = nodes.get(sid)
            if skill_node and skill_node.text.lower() in text_lower:
                edges.append(ResumeEdge(source_id=sid, target_id=bid, relation="used_in"))

    return ResumeGraph(nodes=nodes, edges=edges)
