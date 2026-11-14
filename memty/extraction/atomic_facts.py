"""Local, dependency-free fact extraction from an assistant's answer.

Used by the web bridge's ``[+ Save Facts]`` button. Nothing leaves the device:
the default extractor is regex/heuristics; setting ``MEMTY_OLLAMA_MODEL`` uses a
local Ollama model instead, falling back to heuristics if it is unavailable.
Extraction only *proposes* facts; the user reviews them before anything is saved.

Facts are kept atomic and readable by a chat assistant: headings and pasted
Memty capsules are ignored, bare file paths collapse into one ``files`` fact,
and each code block becomes a one-line summary of what it defines, never code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from urllib import request as urlrequest

from ..vault.credentials import looks_like_credential
from ..vault.ledger import FACT_TOKEN_LIMIT
from ..vault.tokens import estimate_tokens, truncate_tokens

# The review screen and web bridge accept at most 25 facts in one save.
MAX_FACTS = 25
MAX_INPUT_CHARS = 50_000
MAX_CODE_FACTS = 2

_BULLET = re.compile(r"^\s*(?:[-*•●▪]|\d{1,2}[.)])\s+(.*\S)\s*$")
# No "=" separator: "conn = sqlite3.connect(...)" is code, not a fact.
_KEY_VALUE = re.compile(r"^([A-Za-z][\w .'/()-]{0,48}?)\s*[:—]\s+(.{2,})$")
# Lines from code samples: calls, assignments, keywords, statement punctuation.
_CODE = re.compile(
    r"\bself\.|^\s*(?:def|class|import|from|return|const|let|var|function)\b"
    r"|^\s*(?:if|for|while)\b.*:\s*$|=>|[{}]|^\s*[\])]|^\s*[\w.]+\([^)]*\)\s*[:;,]?\s*$|^\s*[\w.\[\]]+\s*[+\-*/]?=\s*\S"
    r"|^\s*(?:#|//)")
# Type annotations such as "namespace: str" or "items: list[str] | None".
_TYPE_HINT = re.compile(
    r"^(?:str|int|float|bool|bytes|dict|list|tuple|set|object|None|Any|Path|"
    r"(?:Optional|Union|List|Dict|Tuple|Set|list|dict|tuple|set)\[.*\])(?:\s*\|\s*None)?"
    r"(?:\s*=\s*.+)?$")
_LINK = re.compile(r"\[([^\]\n]{1,512})\]\(([^)\s]{1,2048})(?:\s+[^)\n]{0,256})?\)")
_CITATION = re.compile(r"\[\d+(?:,\s*\d+)*\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_SLOT_CHARS = re.compile(r"[^a-z0-9]+")

# Capsules a user pasted into the chat must never be re-extracted as new facts.
_CAPSULE = re.compile(r"<memty_state\b.*?(?:</memty_state>|\Z)|\[Memty context.*?(?:\[/Memty\]|\Z)", re.S)
_FENCE = re.compile(r"```([\w+#.-]*)[^\n]*\n(.*?)(?:```|\Z)", re.S)
_CODE_EXT = (r"(?:py|js|mjs|cjs|ts|tsx|jsx|json|md|html|css|scss|sql|toml|ya?ml|sh|ps1|txt|cfg|ini"
             r"|go|rs|java|kt|rb|php|c|h|cpp|cs|swift)")
_PATH = re.compile(r"^(?:[\w.~@-]+[/\\])+[\w.@-]+/?$|^[\w.-]+\.%s$" % _CODE_EXT, re.I)
_FILE_KEY = re.compile(r"\b(?:file|files|path|script|module)\b", re.I)
_ACTION_START = re.compile(r"^(?:use|keep|avoid|never|always|require|allow|reject|disable|enable|prefer|choose)\b", re.I)
_DEFINES = [
    re.compile(r"^\s*(?:async\s+)?def\s+(\w+)", re.M),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)", re.M),
    re.compile(r"\bfunction\s+(\w+)\s*\("),
    re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"),
    re.compile(r"\bCREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?(\w+)", re.I),
]
_FILE_HINT = re.compile(r"^\s*(?:#|//|/\*|<!--|--)\s*((?:[\w.-]+/)*[\w.-]+\.%s)\b" % _CODE_EXT, re.I)
_LANGS = {"py": "Python", "python": "Python", "js": "JavaScript", "javascript": "JavaScript",
          "ts": "TypeScript", "typescript": "TypeScript", "tsx": "TypeScript", "jsx": "JavaScript",
          "sql": "SQL", "sh": "Shell", "bash": "Shell", "json": "JSON", "html": "HTML", "css": "CSS"}


def _looks_like_code(raw: str, key: str | None, value: str) -> bool:
    if _CODE.search(raw) or _TYPE_HINT.match(value):
        return True
    # "snake_case_key: value" with a dotted call or path in the value.
    return bool(key and "_" in key and " " not in key and re.search(r"\w\.\w+\(", value))


def _clean(text: str) -> str:
    def keep_link(match: re.Match) -> str:
        label, target = match.group(1), match.group(2)
        if re.fullmatch(r"\d+(?:,\s*\d+)*", label):
            return ""  # a numbered citation, not the content it cites
        if target.startswith(("http://", "https://")) and label != target:
            return f"{label} ({target})"
        return label

    if "](" in text:
        text = _LINK.sub(keep_link, text)
    text = _CITATION.sub("", text)
    # Remove Markdown formatting, not meaningful characters such as C#, *,
    # comparisons, or underscores inside identifiers.
    text = re.sub(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"^\s*(?:#{1,6}\s+|>\s*)", "", text)
    return re.sub(r"\s+", " ", text).strip(" -:;,")


_STOPWORDS = frozenset("""a an the this that these those it its is are was were be been being am
of to in on at by for with from as into onto over under about and or but nor so yet if then than
i you he she we they me my your our their his her them us do does did done have has had will would
can could should may might must shall not no only also just very more most some any all each every
which who whom whose what when where why how there here""".split())

_GENERIC_TITLE_WORDS = frozenset("""pointed out critical problem issue important note noted identified
actually simply often typically generally following example consider key main thing thing issues using
used use when while where because instead across before after make makes made makes much many""".split())
_TOPIC_HINTS = (
    (re.compile(r"\btokens?\b|\btokeni[sz]ation\b", re.I), "tokens"),
    (re.compile(r"\bschemas?\b", re.I), "schema"),
    (re.compile(r"\bauth(?:entication|orization)?\b", re.I), "auth"),
    (re.compile(r"\bprivac(?:y|e)\b|\bprivate\b", re.I), "privacy"),
    (re.compile(r"\brate[ -]?limit(?:er|ing)?\b", re.I), "rate_limit"),
    (re.compile(r"\bcach(?:e|es|ing)\b", re.I), "cache"),
    (re.compile(r"\bmemor(?:y|ies)\b", re.I), "memory"),
    (re.compile(r"\blatenc(?:y|ies)\b", re.I), "latency"),
    (re.compile(r"\b(?:stor(?:e|age)|database|vault)\b", re.I), "storage"),
)


def _title_for(value: str, raw: str = "") -> str:
    """Prefer named terms, acronyms and inline identifiers over filler words."""
    source = raw or value
    terms: list[str] = []

    def add(term: str) -> None:
        normalized = _SLOT_CHARS.sub("_", term.casefold()).strip("_")
        if normalized and normalized not in terms and normalized not in _GENERIC_TITLE_WORDS:
            terms.append(normalized)

    for acronym in re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", source):
        add(acronym)
    for identifier in re.findall(r"`([^`\n]{1,80})`", source):
        identifier = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", identifier)
        add(identifier)
    if not terms:
        for match in re.finditer(r"\b[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)*\b", value):
            if match.start() > 0 and match.group().casefold() not in _STOPWORDS:
                add(match.group())
    if terms:
        for pattern, hint in _TOPIC_HINTS:
            if pattern.search(value) and hint not in terms:
                add(hint)
                break
        return "_".join(terms[:3])
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9+#-]*", value)
             if w.casefold() not in _STOPWORDS and w.casefold() not in _GENERIC_TITLE_WORDS]
    return "_".join(words[:3]).casefold()


def _slot_for(key: str | None, value: str, raw: str = "") -> str:
    for candidate in (key, _title_for(value, raw)):
        if candidate:
            slot = _SLOT_CHARS.sub("_", candidate.casefold()).strip("_")[:48].strip("_")
            if slot and slot[0].isalnum():
                return slot
    return "note_" + hashlib.sha1(value.casefold().encode("utf-8")).hexdigest()[:8]


def _is_heading(value: str) -> bool:
    """Title-cased, unpunctuated lines are section headings, not facts."""
    if value[-1:] in ".!:;" or len(value.split()) > 12:
        return False
    words = [w.strip("()[],\"'") for w in value.split()]
    words = [w for w in words if w and w[0].isalpha()]
    return len(words) >= 2 and sum(w[0].isupper() for w in words) / len(words) >= 0.7


def _is_path(key: str | None, value: str) -> bool:
    if " " in value or not _PATH.match(value):
        return False
    return "/" in value or "\\" in value or not key or bool(_FILE_KEY.search(key))


def _fact(line: str) -> dict | None:
    raw = line.strip()
    if raw.endswith(":"):
        return None  # introductory line or heading
    line = _clean(line)
    if len(line) < 3 or line.endswith("?"):
        return None
    key, value = None, line
    match = _KEY_VALUE.match(line)
    if (match and len(match.group(1).split()) <= 5
            and not re.match(r"^(?:you|we|i|pointed|noted|identified)\b", match.group(1), re.I)):
        key, value = match.group(1).strip(), match.group(2).strip()
    if _is_path(key, value):
        return {"slot": "files", "value": value, "path": True}
    if _looks_like_code(raw, key, value):
        return None
    action = bool(_ACTION_START.match(value))
    if not key and (value.endswith(":") or len(value.split()) < 2 or
                    ((len(value.split()) < 3 or _is_heading(value)) and not action)):
        return None  # fragments and headings are not atomic facts
    if not value:
        return None
    return {"slot": _slot_for(key, value, raw), "value": value}


def summarize_code(code: str, lang: str = "") -> dict | None:
    """One readable fact about a code block: its language, file, and what it defines."""
    names: list[str] = []
    for pattern in _DEFINES:
        for match in pattern.finditer(code):
            name = match.group(1)
            if not name.startswith("__") and name not in names:
                names.append(name)
    if not names:
        return None
    lang = _LANGS.get(lang.casefold(), lang) if lang else ""
    if not lang:
        lang = ("Python" if re.search(r"^\s*(?:async\s+)?(?:def|class)\s", code, re.M) else
                "SQL" if re.search(r"\bCREATE\s+TABLE\b", code, re.I) else "JavaScript")
    file_hint = _FILE_HINT.search(code)
    where = f" in {file_hint.group(1)}" if file_hint else ""
    shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
    value = truncate_tokens(f"{lang} code{where} defines {shown}", FACT_TOKEN_LIMIT)
    return {"slot": _slot_for(f"{lang} code", value), "value": value}


def _mostly_code(lines: list[str]) -> bool:
    lines = [line for line in lines if line.strip()]
    return len(lines) >= 3 and sum(bool(_CODE.search(line)) for line in lines) / len(lines) >= 0.6


def _add(facts: list[dict], seen_slots: set[str], slot: str, value: str) -> None:
    unique, counter = slot, 2
    while unique in seen_slots:  # two bullets with the same key: keep both
        unique, counter = f"{slot[:45]}_{counter}", counter + 1
    seen_slots.add(unique)
    facts.append({"slot": unique, "value": value})


def _candidates(lines: list[str]) -> list[str]:
    """Keep prose, list items, and labelled lines in source order."""
    candidates: list[str] = []
    pending: list[str] = []
    kind = ""

    def flush() -> None:
        if pending:
            text = " ".join(pending)
            if kind == "prose":
                sentences: list[str] = []
                for sentence in _SENTENCE.split(text):
                    # Keep a short antecedent beside references such as "It" or
                    # "This" so the resulting fact remains understandable.
                    if (sentences and re.match(r"^(?:it|its|this|that|these|those|they|their|he|she)\b",
                                               sentence, re.I)
                            and estimate_tokens(f"{sentences[-1]} {sentence}") <= FACT_TOKEN_LIMIT):
                        sentences[-1] += " " + sentence
                    else:
                        sentences.append(sentence)
                candidates.extend(sentences)
            else:
                candidates.append(text)
            pending.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            kind = ""
            continue
        bullet = _BULLET.match(line)
        if bullet:
            flush()
            pending.append(bullet.group(1))
            kind = "item"
        elif re.match(r"^\s*#{1,6}\s+", line) or _CODE.search(line):
            flush()
            kind = ""
        elif _KEY_VALUE.match(_clean(line)):
            flush()
            pending.append(stripped)
            kind = "item"
        else:
            if kind == "item" and not line[:1].isspace():
                flush()
                kind = ""
            pending.append(stripped)
            kind = kind or "prose"
    flush()
    return candidates


def _split_value(value: str) -> tuple[list[str], bool]:
    """Pack complete words into bounded parts; report words that cannot fit."""
    parts: list[str] = []
    current = ""
    omitted = False
    for sentence in _SENTENCE.split(value):
        sentence = sentence.strip()
        if not sentence:
            continue
        combined = f"{current} {sentence}".strip()
        if estimate_tokens(combined) <= FACT_TOKEN_LIMIT:
            current = combined
            continue
        if current:
            parts.append(current)
            current = ""
        if estimate_tokens(sentence) <= FACT_TOKEN_LIMIT:
            current = sentence
            continue
        for word in sentence.split():
            if estimate_tokens(word) > FACT_TOKEN_LIMIT:
                if current:
                    parts.append(current)
                    current = ""
                omitted = True
                continue
            combined = f"{current} {word}".strip()
            if estimate_tokens(combined) > FACT_TOKEN_LIMIT:
                parts.append(current)
                current = word
            else:
                current = combined
    if current:
        parts.append(current)
    return parts, omitted


def _extract_heuristic(text: str, max_facts: int) -> tuple[list[dict], list[str]]:
    original = str(text)
    warnings: list[str] = []
    if len(original) > MAX_INPUT_CHARS:
        warnings.append("Only the first 50,000 characters were processed; select a shorter passage.")
    text = _CAPSULE.sub("\n", original[:MAX_INPUT_CHARS])
    code_blocks = _FENCE.findall(text)
    code_summaries = [summarize_code(body, lang) for lang, body in code_blocks]
    code_facts = [fact for fact in code_summaries if fact][:MAX_CODE_FACTS]
    if any(fact is None for fact in code_summaries) or sum(fact is not None for fact in code_summaries) > MAX_CODE_FACTS:
        warnings.append("Some code blocks were not summarized; check the original text.")
    text = _FENCE.sub("\n", text)
    lines = text.splitlines()
    if _mostly_code(lines):  # the user selected a raw code sample
        fact = summarize_code(text)
        if not fact:
            warnings.append("The selected code could not be summarized; check the original text.")
        return ([fact][:max_facts] if fact else []), warnings
    candidates = _candidates(lines)
    facts: list[dict] = []
    seen_slots: set[str] = set()
    seen_values: set[tuple[str, str]] = set()
    paths: list[str] = []
    split_any = False
    omitted_word = False
    for candidate in candidates:
        fact = _fact(candidate)
        if fact and fact.get("path"):
            if fact["value"] not in paths:
                paths.append(fact["value"])
            continue
        if not fact:
            continue
        identity = (fact["slot"], fact["value"].casefold())
        if identity in seen_values:
            continue
        seen_values.add(identity)
        parts, omitted = _split_value(fact["value"])
        omitted_word |= omitted
        split_any |= len(parts) > 1
        for part in parts:
            _add(facts, seen_slots, fact["slot"], part)
    extras = list(code_facts)
    if paths:
        parts, omitted = _split_value(", ".join(paths))
        omitted_word |= omitted
        split_any |= len(parts) > 1
        extras[0:0] = [{"slot": "files", "value": part} for part in parts]
    for fact in extras:
        _add(facts, seen_slots, fact["slot"], fact["value"])
    if split_any:
        warnings.append("Long passages were split into parts; review the related parts together.")
    if omitted_word:
        warnings.append("An individual word or identifier was too long to save; check the original selection.")
    if len(facts) > max_facts:
        warnings.append(f"Only the first {max_facts} proposed facts are shown. Select the remaining text separately.")
    return facts[:max_facts], warnings


def extract_heuristic(text: str, max_facts: int = MAX_FACTS) -> list[dict]:
    """Extract bounded facts from prose and lists, keeping complete words."""
    return _extract_heuristic(text, max(0, min(int(max_facts), MAX_FACTS)))[0]


def _extract_ollama(text: str, model: str, *, host: str = "http://127.0.0.1:11434",
                    timeout: float = 15.0, max_facts: int = MAX_FACTS) -> tuple[list[dict], list[str]]:
    """Ask a local model for facts, then enforce the ledger's size limits."""
    prompt = ("Extract up to %d durable, atomic facts from the text as JSON: "
              '{"facts": [{"slot": "short_snake_case_key", "value": "one self-contained fact under 25 words"}]}. '
              "Each fact states one thing (a decision, preference, tool, name, number, or date) and "
              "makes sense on its own. Preserve important conditions, negations, numbers and context; "
              "split a long decision into related facts rather than cutting off its ending. "
              "Never copy code: summarize a code block as one fact saying what "
              "it defines or does. Skip headings, questions, and filler. Only facts stated in the text."
              "\n\nTEXT:\n%s" % (max_facts, _CAPSULE.sub("", str(text)[:MAX_INPUT_CHARS])))
    body = json.dumps({"model": model, "prompt": prompt, "format": "json", "stream": False}).encode()
    req = urlrequest.Request(host.rstrip("/") + "/api/generate", data=body,
                             headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=timeout) as response:
        payload = json.loads(json.loads(response.read())["response"])
    facts, seen = [], set()
    warnings = []
    split_any = omitted_word = False
    for item in payload.get("facts", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not str(item.get("value", "")).strip():
            continue
        value = _clean(str(item["value"]))
        slot = _slot_for(str(item.get("slot", "")), value)
        if not value:
            continue
        parts, omitted = _split_value(value)
        split_any |= len(parts) > 1
        omitted_word |= omitted
        for part in parts:
            _add(facts, seen, slot, part)
    if len(str(text)) > MAX_INPUT_CHARS:
        warnings.append("Only the first 50,000 characters were processed; select a shorter passage.")
    if split_any:
        warnings.append("Long passages were split into parts; review the related parts together.")
    if omitted_word:
        warnings.append("An individual word or identifier was too long to save; check the original selection.")
    if len(facts) > max_facts:
        warnings.append(f"Only the first {max_facts} proposed facts are shown. Select the remaining text separately.")
    return facts[:max_facts], warnings


def extract_ollama(text: str, model: str, *, host: str = "http://127.0.0.1:11434",
                   timeout: float = 15.0, max_facts: int = MAX_FACTS) -> list[dict]:
    """Ask a local Ollama model for facts; the result is validated like heuristics."""
    return _extract_ollama(text, model, host=host, timeout=timeout,
                           max_facts=max(0, min(int(max_facts), MAX_FACTS)))[0]


def _flag_credentials(facts: list[dict]) -> list[dict]:
    """Mark proposals holding a key or password; the ledger stores them as SECRET too."""
    for fact in facts:
        if looks_like_credential(fact.get("value", "")):
            fact["sensitivity"] = "SECRET"
    return facts


def extract_facts(text: str, *, max_facts: int = MAX_FACTS) -> dict:
    """Return ``{"facts": [...], "method": "ollama" | "heuristic"}``."""
    model = os.getenv("MEMTY_OLLAMA_MODEL", "").strip()
    if model:
        try:
            facts, warnings = _extract_ollama(text, model, max_facts=max(0, min(int(max_facts), MAX_FACTS)),
                                              host=os.getenv("MEMTY_OLLAMA_HOST", "http://127.0.0.1:11434"))
            if facts:
                result = {"facts": _flag_credentials(facts), "method": "ollama"}
                if warnings:
                    result["warnings"] = warnings
                return result
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Ollama not running or returned junk: fall back to heuristics.
    facts, warnings = _extract_heuristic(text, max(0, min(int(max_facts), MAX_FACTS)))
    result = {"facts": _flag_credentials(facts), "method": "heuristic"}
    if warnings:
        result["warnings"] = warnings
    return result
