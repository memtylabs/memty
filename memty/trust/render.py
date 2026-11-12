"""Terminal output for ``memty inbox``, ``memty receipts`` and ``memty report``."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

# Provider ids used by the browser extension and common MCP client names.
DISPLAY_NAMES = {
    "anthropic": "Claude", "claude": "Claude", "claude-ai": "Claude", "claude-desktop": "Claude Desktop",
    "claude-code": "Claude Code", "openai": "ChatGPT", "chatgpt": "ChatGPT", "google": "Gemini",
    "gemini": "Gemini", "perplexity": "Perplexity", "cursor": "Cursor", "windsurf": "Windsurf",
    "codex": "Codex", "codex-cli": "Codex", "codex-mcp-client": "Codex", "vscode": "VS Code",
    "visual-studio-code": "VS Code", "local": "Local", "ollama": "Ollama", "clipboard": "Clipboard",
    "mcp": "MCP client", "web": "Web",
}


def display_name(client: str) -> str:
    key = str(client or "").casefold()
    if key in DISPLAY_NAMES:
        return DISPLAY_NAMES[key]
    return " ".join(part.capitalize() for part in key.replace("_", "-").split("-") if part) or "Unknown"


def _when(ms: int | None) -> str:
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}{'' if number == 1 else 's'}"


def _join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " & " + names[-1]


def format_inbox(proposals: list[dict[str, Any]]) -> str:
    if not proposals:
        return "Inbox is empty. Agent proposals that would change a saved fact wait here for you."
    lines = []
    for item in proposals:
        before = ("(deleted)" if item["previous_state"] == "DELETED"
                  else json.dumps(item["previous_value"], ensure_ascii=False)
                  if item["previous_value"] is not None else "(new)")
        lock = " [confirmed]" if item["previous_state"] in {"USER_CONFIRMED", "SPEC_LOCKED"} else ""
        lines.append(f"[{item['id']}] {item['namespace']} -> {item['slot']}: {before}{lock} => "
                     f"{json.dumps(item['value'], ensure_ascii=False)} "
                     f"(Proposed by {display_name(item['proposed_by'])})")
        if item.get("reason"):
            lines.append(f"      why: {item['reason']}")
    lines.append("")
    lines.append("memty approve <id>   save as user-confirmed     memty reject <id>   discard")
    return "\n".join(lines)


def format_receipts(receipts: list[dict[str, Any]]) -> str:
    if not receipts:
        return "No receipts yet. One is written each time recall, clip, MCP or the browser serves a capsule."
    lines = []
    for item in receipts:
        if item["secrets_blocked"]:
            outcome = "BLOCKED (SECRET slot matched; nothing sent)"
        else:
            outcome = (f"{item['facts_injected']} fact(s), {item['tokens_injected']} tokens"
                       + (f", {item['redacted']} redacted" if item["redacted"] else ""))
        target = item["namespace"] or "(all namespaces)"
        lines.append(f"#{item['seq']:<5} {_when(item['created_at'])}  {item['channel']:<6} "
                     f"{display_name(item['client']):<14} {target}  {outcome}")
        if item["slots_used"]:
            shown = ", ".join(item["slots_used"][:6])
            more = len(item["slots_used"]) - 6
            lines.append(f"       slots: {shown}" + (f" (+{more} more)" if more > 0 else ""))
    return "\n".join(lines)


def format_report(report: dict[str, Any]) -> str:
    clients = [display_name(name) for name in report["clients"]]
    clients = list(dict.fromkeys(clients))
    across = f" across {_join_names(clients)}" if clients else ""
    headline = (f"{_count(report['capsules_served'], 'capsule')} served{across} | "
                f"{_count(report['distinct_verified_facts_reused'], 'verified fact')} reused | "
                f"~{report['tokens_saved_estimate']:,} tokens saved | "
                f"{_count(report['secret_slots_protected'], 'SECRET slot')} protected")
    lines = [headline, ""]
    if report["requests"]:
        lines.append(f"  Period            {_when(report['first_at'])} -> {_when(report['last_at'])}")
    if report["clients"]:
        lines.append("  By client         " + ", ".join(
            f"{display_name(name)} {count}" for name, count in report["clients"].items()))
    if report["channels"]:
        lines.append("  By channel        " + ", ".join(
            f"{name} {count}" for name, count in report["channels"].items()))
    lines.append(f"  Facts injected    {report['fact_injections']:,} "
                 f"({report['verified_fact_injections']:,} user-confirmed), "
                 f"{report['distinct_facts_reused']:,} distinct")
    lines.append(f"  Tokens            {report['tokens_injected']:,} injected vs "
                 f"~{report['baseline_tokens']:,} for the full namespaces + sources (estimate)")
    lines.append(f"  Privacy           {report['values_redacted']:,} confidential value(s) redacted, "
                 f"{report['secret_requests_blocked']:,} request(s) blocked by a SECRET slot")
    if report["top_facts"]:
        lines.append("  Most reused       " + ", ".join(
            f"{item['slot']} x{item['hits']}" for item in report["top_facts"]))
    if report["pending_proposals"]:
        lines.append(f"  Inbox             {report['pending_proposals']} proposal(s) waiting: memty inbox")
    lines.append("")
    lines.append("Tokens saved is a local estimate (~4 chars/token), not a provider bill.")
    return "\n".join(lines)
