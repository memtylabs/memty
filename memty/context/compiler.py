"""Deterministic <600-token context compiler.

Ranks a namespace's facts for a query and packs them into a ``<memty_state>``
block within the token budget.  Every fact passes through the privacy gate in
:mod:`memty.context.privacy` first.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

from ..vault.ledger import _PROVIDER, _normalize_namespace, _terms
from ..vault.tokens import estimate_tokens, truncate_tokens
from ..vault.vectors import cosine, unpack_vector
from .privacy import LocalRoutingRequired, needs_redaction, provider_allowed, provider_flags
from .render import slot_label

# A stored value is data, never framing: it must not close or forge the capsule's
# own markers, or text saved from one chat could steer the next assistant.
_XML_FRAME = re.compile(r"<(?=\s*/?\s*(?:memty_state|slots|summary|semantic)\b)", re.I)
_PLAIN_FRAME = re.compile(r"\[(?=\s*/?\s*memty\b)", re.I)
_ESCAPED_LT = chr(92) + "u003c"  # backslash-u003c, the JSON escape for "<"


def _json_value(value: str) -> str:
    # The JSON escape for "<" still reads as "<" to a JSON parser, but is no longer a tag.
    return _XML_FRAME.sub(lambda _match: _ESCAPED_LT, json.dumps(value, ensure_ascii=False))


def _plain_value(value: str) -> str:
    return _PLAIN_FRAME.sub("(", " ".join(str(value).split()))


if TYPE_CHECKING:  # pragma: no cover - import cycle only for type checkers
    from ..vault.ledger import MemtyLedger


class ContextCompiler:
    """Compile allowed atomic state, one summary, and semantic snippets."""

    # Section ceilings at the default 600-token budget.  They scale down for a
    # smaller budget and never grow beyond the published maxima for a larger one.
    SLOT_CEILING = 250
    SUMMARY_CEILING = 200
    SEMANTIC_CEILING = 150
    DEFAULT_BUDGET = 600

    def __init__(self, ledger: "MemtyLedger"):
        self.ledger = ledger

    # ------------------------------------------------------------------
    def compile(self, query: str, *, provider: str, token_budget: int = DEFAULT_BUDGET,
                namespace: str | None = None,
                semantic_scores: dict[str, float] | None = None,
                query_embedding: list[float] | None = None,
                strict_namespace: bool = False) -> dict[str, Any]:
        provider = str(provider or "").strip()
        if not _PROVIDER.fullmatch(provider):
            raise ValueError("provider is required and must be a provider identifier")
        if not isinstance(token_budget, int) or not 1 <= token_budget <= 20_000:
            raise ValueError("token_budget must be an integer between 1 and 20000")
        query = "" if query is None else str(query).strip()
        namespace = _normalize_namespace(namespace) if namespace else None

        provider_key, local, trusted = provider_flags(provider, self.ledger.trusted_providers)
        query_terms = _terms(query)
        scores = {str(key): float(value) for key, value in (semantic_scores or {}).items()}

        with self.ledger._connect() as db:
            rows = self.ledger.candidate_facts(db, query_terms, namespace, set(scores), query_embedding)
            ranked: list[tuple[float, dict[str, Any], sqlite3.Row]] = []
            for row in rows:
                fact = self.ledger._fact(row, include_embedding=False)
                if (strict_namespace and fact["namespace"] != namespace) or fact["tombstone"] or not provider_allowed(fact, provider_key, trusted):
                    continue
                overlap = (len(query_terms & _terms(
                    f"{fact['namespace']} {fact['slot']} {fact['value']}")) / len(query_terms)
                    if query_terms else 0.0)
                semantic = max(0.0, min(1.0, scores.get(fact["id"], 0.0)))
                if query_embedding and row["embedding"]:
                    semantic = max(semantic, max(0.0, min(
                        1.0, cosine(query_embedding, unpack_vector(row["embedding"])))))
                if query_terms and overlap == 0.0 and semantic < 0.15 and not (
                        namespace and fact["namespace"] == namespace):
                    continue
                if not query_terms and not namespace and not query_embedding:
                    continue
                score = 0.55 * semantic + 0.45 * overlap
                if namespace and fact["namespace"] == namespace:
                    score += 0.15
                if fact["verification_state"] in {"USER_CONFIRMED", "SPEC_LOCKED"}:
                    score += 0.05
                score += 0.05 * float(fact["confidence"])
                fact["_semantic_score"] = semantic
                ranked.append((score, fact, row))
            # Without a question there is nothing to be relevant to: newest facts first,
            # so a fact saved a minute ago is never crowded out by older A-Z slots.
            # With a question, ties still go to the most recently saved fact.
            browsing = not query_terms and not query_embedding
            ranked.sort(key=lambda item: (0.0 if browsing else -item[0], -int(item[1]["updated_at"] or 0),
                                          item[1]["namespace"], item[1]["slot"], item[1]["id"]))

            # Hard privacy gate: a SECRET fact that matches this query forces
            # local routing regardless of the provider's allow-list.
            if not local:
                for _, fact, _row in ranked:
                    if fact["sensitivity"] == "SECRET":
                        raise LocalRoutingRequired(provider, namespace=fact["namespace"],
                                                   slot=fact["slot"])

            summary = self._select_summary(db, query_terms, namespace, query_embedding,
                                           provider_key, trusted)
            if strict_namespace and summary is not None and summary["namespace"] != namespace:
                summary = None
            sensitive_summary = False
            if summary is not None and not trusted:
                sensitive_summary = self.ledger.namespace_has_sensitive(db, summary["namespace"])
            if sensitive_summary:
                summary = None

        return self._pack(ranked, summary, provider=provider, provider_key=provider_key,
                          local=local, trusted=trusted, token_budget=token_budget,
                          namespace=namespace, eligible_count=len(ranked))

    def compile_selected(self, namespace: str, fact_ids: list[str], *, provider: str,
                         token_budget: int = 2000) -> dict[str, Any]:
        """Render one explicitly chosen context without mixing other namespace facts."""
        namespace = _normalize_namespace(namespace)
        provider = str(provider or "").strip()
        if not _PROVIDER.fullmatch(provider):
            raise ValueError("provider is required and must be a provider identifier")
        if not isinstance(token_budget, int) or not 1 <= token_budget <= 2000:
            raise ValueError("token_budget must be an integer between 1 and 2000")
        if (not isinstance(fact_ids, list) or not 1 <= len(fact_ids) <= 25
                or any(not isinstance(item, str) for item in fact_ids)
                or len(set(fact_ids)) != len(fact_ids)):
            raise ValueError("a context must contain 1-25 distinct fact IDs")
        provider_key, local, trusted = provider_flags(provider, self.ledger.trusted_providers)
        placeholders = ",".join("?" for _ in fact_ids)
        with self.ledger._connect() as db:
            rows = db.execute(
                f"SELECT * FROM atomic_facts WHERE user_id=? AND namespace=? AND tombstone=0 AND id IN ({placeholders})",
                (self.ledger.user_id, namespace, *fact_ids)).fetchall()
        by_id = {row["id"]: self.ledger._fact(row) for row in rows}
        if len(by_id) != len(fact_ids):
            raise ValueError("context changed; choose it again")
        allowed = []
        for fact_id in fact_ids:
            fact = by_id[fact_id]
            if not provider_allowed(fact, provider_key, trusted):
                continue
            if fact["sensitivity"] == "SECRET" and not local:
                raise LocalRoutingRequired(provider, namespace=namespace, slot=fact["slot"])
            private = needs_redaction(fact, provider_key, trusted)
            allowed.append((fact, "[private]" if private else fact["value"], private))
        header, footer = "[Memty context]", "[/Memty]"
        lines: list[str] = []
        included: list[str] = []
        redacted = 0
        for fact, value, private in allowed:
            line = f"{len(lines) + 1}. {slot_label(fact['slot'])}: {_plain_value(value)}"
            candidate = "\n".join([header, *lines, line, footer])
            if estimate_tokens(candidate) > token_budget:
                break
            lines.append(line)
            included.append(fact["id"])
            redacted += int(private)
        text = "\n".join([header, *lines, footer]) if lines else ""
        return {"text": text, "approx_tokens": estimate_tokens(text), "facts": len(lines),
                "omitted": len(fact_ids) - len(lines), "redacted": redacted,
                "fact_ids": included}

    # ------------------------------------------------------------------
    def _select_summary(self, db: sqlite3.Connection, query_terms: set[str],
                        namespace: str | None, query_embedding: list[float] | None,
                        provider_key: str, trusted: bool) -> dict[str, Any] | None:
        candidates = self.ledger.candidate_summaries(db, query_terms, namespace, query_embedding)
        best: tuple[float, sqlite3.Row] | None = None
        for row in candidates:
            overlap = (len(query_terms & _terms(f"{row['namespace']} {row['summary_text']}"))
                       / len(query_terms) if query_terms else 0.0)
            semantic = (max(0.0, min(1.0, cosine(query_embedding, unpack_vector(row["embedding"]))))
                        if query_embedding and row["embedding"] else 0.0)
            score = 0.55 * semantic + 0.45 * overlap
            if namespace and row["namespace"] == namespace:
                score += 0.5
            elif not query_terms:
                continue
            if score > 0 and (best is None or score > best[0]):
                best = (score, row)
        if best is None:
            return None
        row = best[1]
        return {"namespace": row["namespace"], "summary_text": row["summary_text"],
                "token_count": row["token_count"], "updated_at": row["updated_at"]}

    # ------------------------------------------------------------------
    def _pack(self, ranked: list[tuple[float, dict[str, Any], sqlite3.Row]], summary: dict[str, Any] | None,
              *, provider: str, provider_key: str, local: bool, trusted: bool,
              token_budget: int, namespace: str | None, eligible_count: int) -> dict[str, Any]:
        header = f'<memty_state v="1" provider="{provider}">'
        if estimate_tokens(header + "</memty_state>") > token_budget:
            return self._empty(provider, token_budget, eligible_count)

        overhead = estimate_tokens(header + "</memty_state><slots></slots><summary></summary><semantic></semantic>")
        usable = max(0, token_budget - overhead)
        slot_cap = min(self.SLOT_CEILING, int(usable * 0.42))
        summary_cap = min(self.SUMMARY_CEILING, int(usable * 0.33))
        semantic_cap = min(self.SEMANTIC_CEILING, max(0, usable - slot_cap - summary_cap))

        slots: list[str] = []
        semantic_lines: list[str] = []
        citations: list[dict[str, Any]] = []
        redactions: dict[str, str] = {}
        placeholder_by_id: dict[str, str] = {}
        used: set[str] = set()
        counter = 0

        def redact(fact: dict[str, Any]) -> bool:
            return needs_redaction(fact, provider_key, local or trusted)

        def placeholder_for(fact: dict[str, Any]) -> str:
            nonlocal counter
            placeholder = placeholder_by_id.get(fact["id"])
            if placeholder is None:
                counter += 1
                placeholder = f"<MEMTY_REDACTED_SLOT_{counter}>"
                placeholder_by_id[fact["id"]] = placeholder
                redactions[placeholder] = fact["value"]
            return placeholder

        def line_for(fact: dict[str, Any], value: str) -> str:
            return f"{fact['namespace']}.{fact['slot']}={_json_value(value)}"

        def probe_line(fact: dict[str, Any]) -> str:
            # Use a placeholder-shaped value while checking the budget so we do
            # not create a redaction mapping for a fact that never gets injected.
            value = "<MEMTY_REDACTED_SLOT_99>" if redact(fact) else fact["value"]
            return line_for(fact, value)

        def citation(fact: dict[str, Any], section: str) -> dict[str, Any]:
            return {"id": fact["id"], "namespace": fact["namespace"], "slot": fact["slot"],
                    "value": placeholder_by_id.get(fact["id"], fact["value"]),
                    "verification_state": fact["verification_state"],
                    "sensitivity": fact["sensitivity"], "section": section}

        def render(slot_lines: list[str], summary_line: str | None,
                   semantic_snippets: list[str]) -> str:
            parts = [header]
            if slot_lines:
                parts.extend(["<slots>", *slot_lines, "</slots>"])
            if summary_line:
                parts.append(summary_line)
            if semantic_snippets:
                parts.extend(["<semantic>", *semantic_snippets, "</semantic>"])
            parts.append("</memty_state>")
            return "\n".join(parts)

        # Cheap additive accounting avoids re-tokenizing the whole block for
        # every candidate.  The final render plus safety loop is exact.
        base_tokens = estimate_tokens(header + "</memty_state>") + 4
        slots_tag_tokens = estimate_tokens("<slots></slots>")
        semantic_tag_tokens = estimate_tokens("<semantic></semantic>")

        def fits(extra_slot: int = 0, extra_semantic: int = 0) -> bool:
            total = base_tokens + extra_slot + extra_semantic
            if slots or extra_slot:
                total += slots_tag_tokens
            if summary_line:
                total += estimate_tokens(summary_line)
            if semantic_lines or extra_semantic:
                total += semantic_tag_tokens
            return total <= token_budget

        summary_line: str | None = None
        if summary is not None:
            summary_namespace = summary["namespace"]
            text = truncate_tokens(summary["summary_text"], max(1, summary_cap - 12))
            candidate = f'<summary ns="{escape(summary_namespace)}">{escape(text)}</summary>'
            if base_tokens + estimate_tokens(candidate) <= token_budget:
                summary_line = candidate

        slot_used = 0
        for _score, fact, _row in ranked:
            if len(slots) >= 32:
                break
            if fact["id"] in used:
                continue
            probe = probe_line(fact)
            cost = estimate_tokens(probe)
            if slot_used + cost > slot_cap:
                continue
            if not fits(extra_slot=cost + 1):
                continue
            value = placeholder_for(fact) if redact(fact) else fact["value"]
            slots.append(line_for(fact, value))
            used.add(fact["id"])
            slot_used += cost
            citations.append(citation(fact, "slots"))

        semantic_used = 0
        semantic_candidates = sorted(
            ranked,
            key=lambda item: (-float(item[1].get("_semantic_score", 0.0)), -item[0],
                              item[1]["namespace"], item[1]["slot"], item[1]["id"]))
        for _score, fact, _row in semantic_candidates:
            if len(semantic_lines) >= 3:
                break
            if fact["id"] in used:
                continue
            probe = probe_line(fact)
            cost = estimate_tokens(probe)
            if semantic_used + cost > semantic_cap:
                continue
            if not fits(extra_semantic=cost + 1):
                continue
            value = placeholder_for(fact) if redact(fact) else fact["value"]
            semantic_lines.append(line_for(fact, value))
            used.add(fact["id"])
            semantic_used += cost
            citations.append(citation(fact, "semantic"))

        text = render(slots, summary_line, semantic_lines)
        # Final hard guarantee, even if a caller changed the ceilings above.
        def drop_last_citation(section: str) -> None:
            for index in range(len(citations) - 1, -1, -1):
                if citations[index].get("section") == section:
                    citations.pop(index)
                    return

        while estimate_tokens(text) > token_budget and (semantic_lines or summary_line or slots):
            if semantic_lines:
                semantic_lines.pop()
                drop_last_citation("semantic")
            elif summary_line:
                summary_line = None
            else:
                slots.pop()
                drop_last_citation("slots")
            text = render(slots, summary_line, semantic_lines)

        if not slots and summary_line is None and not semantic_lines:
            return self._empty(provider, token_budget, eligible_count)

        if summary_line is not None:
            citations.insert(0, {"type": "summary", "namespace": summary["namespace"],
                                 "value": summary["summary_text"], "token_count": summary["token_count"],
                                 "section": "summary"})

        redactions = {key: value for key, value in redactions.items() if key in text}
        return {"text": text, "citations": citations, "redactions": redactions,
                "provider": provider, "approx_tokens": estimate_tokens(text),
                "token_budget": token_budget, "eligible_count": eligible_count,
                "injected_count": sum(1 for item in citations if item.get("type") != "summary"),
                "sections": {"slots": len(slots), "summary": int(summary_line is not None),
                             "semantic": len(semantic_lines)},
                "requires_local": False}

    @staticmethod
    def _empty(provider: str, token_budget: int, eligible_count: int) -> dict[str, Any]:
        return {"text": "", "citations": [], "redactions": {}, "provider": provider,
                "approx_tokens": 0, "token_budget": token_budget,
                "eligible_count": eligible_count, "injected_count": 0,
                "sections": {"slots": 0, "summary": 0, "semantic": 0},
                "requires_local": False}
