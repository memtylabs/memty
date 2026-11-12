"""Compare one reproducible five-turn memory handoff workload.

Offline counts are Memty's estimates of supplied payloads, not provider bills.
The optional live mode calls Claude and Perplexity APIs with synthetic data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib import error as urlerror
from urllib import request as urlrequest

from memty.vault.ledger import MemtyLedger
from memty.vault.tokens import estimate_tokens

FIXTURE = Path(__file__).with_name("architecture.json")
MODES = ("full_document_replay", "simulated_retrieval", "memty_selected_context")
SIMULATED_TOOLS = [
    {"name": "search_memory", "description": "Search saved architecture documents.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "read_memory", "description": "Read the retrieved document chunks.",
     "input_schema": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
                      "required": ["ids"]}},
]


def load_fixture(path: Path = FIXTURE) -> tuple[dict, str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if len(data.get("turns", [])) != 5 or len(data.get("facts", [])) != 10:
        raise ValueError("fixture must contain five turns and ten facts")
    slots = [fact["slot"] for fact in data["facts"]]
    if len(set(slots)) != len(slots):
        raise ValueError("fixture slots must be distinct")
    for turn in data["turns"]:
        if turn["provider"] not in {"claude", "perplexity", "gemini"} or any(key not in slots for key in turn["expected"]):
            raise ValueError("fixture contains an invalid provider or expected slot")
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return data, hashlib.sha256(canonical).hexdigest()


def build_payloads(fixture: dict) -> dict[str, list[str]]:
    facts = fixture["facts"]
    full = "\n\n".join(f"Document {i + 1}: {fact['source']}" for i, fact in enumerate(facts))
    retrieved = ("Simulated tool definitions: " + json.dumps(SIMULATED_TOOLS, sort_keys=True) + "\n" +
                 "\n".join(f"Chunk {i + 1}: {fact['chunk']}" for i, fact in enumerate(facts)))
    with tempfile.TemporaryDirectory(prefix="memty-benchmark-") as tmp:
        with MemtyLedger(Path(tmp) / "benchmark.sqlite3") as ledger:
            saved = ledger.record_context(fixture["namespace"], [
                {"slot": fact["slot"], "value": fact["value"]} for fact in facts])
            ids = [ledger.find(fixture["namespace"], fact["slot"])["id"] for fact in saved["saved"]]
            capsules = []
            for turn in fixture["turns"]:
                provider = {"claude": "anthropic", "perplexity": "perplexity", "gemini": "google"}[turn["provider"]]
                capsule = ledger.context_selected(fixture["namespace"], ids, provider=provider, token_budget=2000)
                capsules.append(capsule["text"])
    return {"full_document_replay": [full] * 5, "simulated_retrieval": [retrieved] * 5,
            "memty_selected_context": capsules}


def offline_report(fixture: dict, fixture_hash: str, payloads: dict[str, list[str]]) -> dict:
    values = {fact["slot"]: fact["value"] for fact in fixture["facts"]}
    rows = {}
    for mode in MODES:
        turns = []
        for turn, payload in zip(fixture["turns"], payloads[mode]):
            missing = [slot for slot in turn["expected"] if values[slot].casefold() not in payload.casefold()]
            turns.append({"provider": turn["provider"], "question": turn["question"],
                          "estimated_memory_tokens": estimate_tokens(payload),
                          "expected_values_present": len(turn["expected"]) - len(missing),
                          "expected_values_total": len(turn["expected"]), "missing_slots": missing})
        rows[mode] = {"turns": turns,
                      "estimated_memory_tokens_total": sum(t["estimated_memory_tokens"] for t in turns),
                      "expected_values_present": sum(t["expected_values_present"] for t in turns),
                      "expected_values_total": sum(t["expected_values_total"] for t in turns)}
    memty_total = rows["memty_selected_context"]["estimated_memory_tokens_total"]
    reductions = {baseline: round(100 * (1 - memty_total / rows[baseline]["estimated_memory_tokens_total"]), 1)
                  for baseline in ("full_document_replay", "simulated_retrieval")
                  if rows[baseline]["estimated_memory_tokens_total"]}
    return {"mode": "offline_payload_simulation", "fixture": fixture["name"], "fixture_sha256": fixture_hash,
            "token_counter": "memty.vault.tokens.estimate_tokens (heuristic, not a provider tokenizer)",
            "scope": "Memory payload only; no provider, model answer, actual MCP roundtrip, billing or latency measured.",
            "retrieval_baseline": "Curated oracle chunks plus illustrative tool definitions; not a real RAG or MCP product.",
            "continuity_metric": "Exact expected value appears in supplied context; not assistant recall accuracy.",
            "estimated_memory_payload_reduction_percent": reductions,
            "results": rows}


def _post(url: str, headers: dict, body: dict) -> dict:
    req = urlrequest.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=120) as response:
            return json.load(response)
    except urlerror.HTTPError as error:
        # Do not print provider response bodies, request headers, or credentials.
        raise RuntimeError(f"Provider request failed with HTTP {error.code}") from error


def _provider_response(provider: str, model: str, key: str, prompt: str) -> tuple[str, dict, str]:
    if provider == "claude":
        data = _post("https://api.anthropic.com/v1/messages",
                     {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
                     {"model": model, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]})
        text = "\n".join(item.get("text", "") for item in data.get("content", []) if item.get("type") == "text")
    elif provider == "gemini":
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
            raise ValueError("Invalid Gemini model ID")
        data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     {"Content-Type": "application/json", "x-goog-api-key": key},
                     {"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"maxOutputTokens": 400, "thinkingConfig": {"thinkingBudget": 0}}})
        text = "\n".join(part.get("text", "") for item in data.get("candidates", [])
                         for part in item.get("content", {}).get("parts", []) if not part.get("thought"))
        gemini_usage = data.get("usageMetadata") or {}
        prompt_tokens = gemini_usage.get("promptTokenCount")
        total_tokens = gemini_usage.get("totalTokenCount")
        usage = {"input_tokens": prompt_tokens,
                 "output_tokens": total_tokens - prompt_tokens if isinstance(total_tokens, int) and isinstance(prompt_tokens, int) else None}
        if not text or not isinstance(usage["output_tokens"], int):
            raise RuntimeError("gemini response did not include answer text and token usage")
        return text, usage, str(data.get("modelVersion") or model)
    elif provider == "perplexity":
        data = _post("https://api.perplexity.ai/v1/agent",
                     {"Content-Type": "application/json", "Authorization": "Bearer " + key},
                     {"model": model, "input": prompt, "max_output_tokens": 400, "max_steps": 1,
                      "tools": [], "store": False})
        if data.get("status") != "completed":
            raise RuntimeError("Perplexity response did not complete")
        text = "\n".join(part.get("text", "") for item in data.get("output", [])
                         if item.get("type") == "message" for part in item.get("content", [])
                         if part.get("type") == "output_text")
    else:
        raise ValueError("Unsupported provider")
    usage = data.get("usage") or {}
    if not text or not isinstance(usage.get("input_tokens"), int) or not isinstance(usage.get("output_tokens"), int):
        raise RuntimeError(f"{provider} response did not include answer text and token usage")
    return text, usage, str(data.get("model") or model)


def _answers(text: str) -> dict:
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def live_report(fixture: dict, fixture_hash: str, payloads: dict[str, list[str]],
                models: dict[str, str], keys: dict[str, str]) -> dict:
    providers = {turn["provider"] for turn in fixture["turns"]}
    if any(not keys.get(provider) or not models.get(provider) for provider in providers):
        raise ValueError("live mode needs both provider API keys and explicit model IDs")
    values = {fact["slot"]: fact["value"] for fact in fixture["facts"]}
    results = {}
    for mode in MODES:
        history = []
        turns = []
        for index, turn in enumerate(fixture["turns"]):
            keys_needed = turn["expected"]
            prompt = ("Use only the provided synthetic architecture context and previous turns. "
                      "Return one JSON object whose requested keys contain the exact values from the context. "
                      "Do not infer missing values; use null if unknown.\n\n"
                      + "Previous turns:\n" + "\n".join(history) + "\n\n"
                      + "Context:\n" + payloads[mode][index] + "\n\nQuestion: " + turn["question"]
                      + "\nRequested keys: " + ", ".join(keys_needed))
            started = time.perf_counter()
            answer, usage, actual_model = _provider_response(turn["provider"], models[turn["provider"]],
                                                               keys[turn["provider"]], prompt)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            parsed = _answers(answer)
            matches = sum(isinstance(parsed.get(slot), str) and
                          " ".join(parsed[slot].split()).casefold() == " ".join(values[slot].split()).casefold()
                          for slot in keys_needed)
            turns.append({"provider": turn["provider"], "model": actual_model,
                          "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                          "latency_ms": elapsed_ms, "exact_values_returned": matches,
                          "expected_values_total": len(keys_needed), "answer": answer})
            history.append("User: " + turn["question"] + "\nAssistant: " + answer)
        results[mode] = {"turns": turns, "input_tokens": sum(t["input_tokens"] for t in turns),
                         "output_tokens": sum(t["output_tokens"] for t in turns),
                         "exact_values_returned": sum(t["exact_values_returned"] for t in turns),
                         "expected_values_total": sum(t["expected_values_total"] for t in turns)}
    return {"mode": "live_provider_calls", "fixture": fixture["name"], "fixture_sha256": fixture_hash,
            "providers": [turn["provider"] for turn in fixture["turns"]],
            "scope": "Five alternating provider API calls per mode; prior synthetic Q&A is replayed across providers. Provider substitutions are listed separately from the original fixture digest.",
            "retrieval_baseline": "Curated snippets and illustrative schemas in prompt text; no actual RAG or MCP server was invoked.",
            "token_accounting": "Provider-reported complete request input and output usage; includes question and prior answers.",
            "roundtrips": "Five model requests per mode; no actual model tool calls were made.", "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="make 15 billable provider API requests")
    parser.add_argument("--anthropic-model", help="explicit Claude model ID for --live")
    parser.add_argument("--perplexity-model", help="explicit Perplexity Agent API provider/model ID for --live")
    parser.add_argument("--second-provider", choices=("perplexity", "gemini"), default="perplexity")
    parser.add_argument("--gemini-model", help="Gemini API model ID for --live --second-provider gemini")
    parser.add_argument("--output", type=Path, help="write JSON results to this file")
    args = parser.parse_args()
    fixture, digest = load_fixture()
    if args.live and args.second_provider == "gemini":
        for turn in fixture["turns"]:
            if turn["provider"] == "perplexity":
                turn["provider"] = "gemini"
    payloads = build_payloads(fixture)
    if args.live:
        keys = {"claude": os.getenv("ANTHROPIC_API_KEY", ""), "perplexity": os.getenv("PERPLEXITY_API_KEY", ""),
                "gemini": os.getenv("GEMINI_API_KEY", "")}
        models = {"claude": args.anthropic_model or "", "perplexity": args.perplexity_model or "", "gemini": args.gemini_model or ""}
        try:
            report = live_report(fixture, digest, payloads, models, keys)
        except (ValueError, RuntimeError, OSError) as error:
            raise SystemExit(str(error)) from error
    else:
        report = offline_report(fixture, digest, payloads)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
