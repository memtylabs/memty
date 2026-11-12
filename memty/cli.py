"""Small standard-library CLI for inspecting and operating a Memty vault."""

from __future__ import annotations

import argparse
import json
from importlib import metadata
import sys

from .context.privacy import LocalRoutingRequired
from .context.render import render_plain_with_count
from .vault.tokens import estimate_tokens
from .vault.paths import default_user_id, default_vault_path
from .vault.ledger import MemtyLedger
from .trust.render import format_inbox, format_receipts, format_report
from .trust.receipts import log_blocked, log_served


def _version() -> str:
    """Read the installed distribution version without starting the vault."""
    try:
        return metadata.version("memty")
    except metadata.PackageNotFoundError:
        return "development"


def _welcome() -> None:
    """Show a portable, read-only introduction when no command is supplied."""
    wordmark = r"""
   __  __  _____  __  __  _____ __   __
  |  \/  || ____||  \/  ||_   _|\ \ / /
  | |\/| ||  _|  | |\/| |  | |   \ V /
  | |  | || |___ | |  | |  | |    | |
  |_|  |_||_____||_|  |_|  |_|    |_|
""".strip("\n")
    print(wordmark)
    print(f"""
    \n
  Local memory for AI assistants  |  v{_version()}
  ------------------------------------------------------------

  Memty keeps your facts, decisions, and context in a
  user-owned local vault. Connect supported assistants to
  share relevant memory through the MCP bridge.

  GET STARTED

  memty connect      Connect your AI assistants
  memty remember     Save a fact to your vault
  memty recall       Retrieve relevant context
  memty clip NS      Copy a namespace capsule for any AI
  memty serve        Bridge browser assistants (--autostart once)
  memty extension    Install the browser extension folder
  memty scan         Bootstrap project facts from manifests (0 tokens)
  memty inbox        Review facts your agents proposed
  memty report       See what was served, reused, and protected
  memty stats        View vault statistics
  memty --help       See all commands

  TRY IT

  memty remember project.demo editor "VS Code"
  memty recall "editor" --namespace project.demo

  ------------------------------------------------------------
  Your memory stays under your control.
""".strip("\n"))


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _ledger(args) -> MemtyLedger:
    trusted = [item.strip() for item in (args.trusted_provider or []) if item.strip()]
    from .runtime.daemon import DaemonLedger
    return DaemonLedger(args.db, args.user, trusted_providers=trusted)


def _serve(args) -> None:
    from .integrations.browser import bridge as web_bridge
    if args.no_autostart:
        from .runtime.autostart import uninstall
        _print({**uninstall(), **web_bridge.stop_background(args.db)})
        return
    if args.stop:
        _print(web_bridge.stop_background(args.db))
        return
    token = web_bridge.load_or_create_token(args.db, rotate=args.new_token)
    if args.show_token or args.new_token:
        print(token)
        return
    if args.background or args.autostart:
        extra = {}
        if args.autostart:
            from .runtime.autostart import install
            extra = install(args.db, args.user, args.port)
        _print({**web_bridge.start_background(args.db, args.user, port=args.port,
                                              allowed_origins=args.allow_origin), **extra,
                "url": f"http://127.0.0.1:{args.port}",
                "next": "Load the Memty Bridge extension; it pairs itself automatically."})
        return
    print(f"Memty bridge on http://127.0.0.1:{args.port} (Ctrl+C to stop)", file=sys.stderr)
    print("The browser extension pairs itself on first use.", file=sys.stderr)
    try:
        web_bridge.serve(args.db, args.user, port=args.port, allowed_origins=args.allow_origin,
                         quiet=not args.verbose)
    except OSError as error:
        raise SystemExit(f"Could not listen on 127.0.0.1:{args.port}: {error}")


def _pair(args) -> None:
    from .integrations.browser import bridge as web_bridge
    web_bridge.load_or_create_token(args.db)
    try:
        # Verifies that a bridge already on the port serves *this* vault; pairing a
        # different vault's bridge would silently never take effect.
        web_bridge.start_background(args.db, args.user, port=args.port)
    except RuntimeError as error:
        raise SystemExit(
            f"Cannot pair: {error}\n"
            f"Another Memty bridge (for a different vault or user, or an older version) is using "
            f"127.0.0.1:{args.port}. Stop it with `memty --db <that vault> serve --stop`, or end the "
            f"process listening on port {args.port}, then run `memty pair` again.")
    web_bridge.open_pairing(args.db, args.seconds)
    print(f"Pairing is open for {args.seconds // 60 or 1} minute(s).")
    print("In your browser, click Try again on the Memty page, or use Memty in any chat.")
    print("Only the next browser extension that connects is added.")


def _extension(args) -> None:
    from .integrations.browser import installer as extension
    try:
        result = extension.install(args.dir)
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"Could not install the browser extension: {error}")
    print(f"Memty Bridge v{result['version']} is ready in:")
    print(f"  {result['path']}")
    print()
    print("Load it once (Chrome, Edge, or Brave):")
    print("  1. Open chrome://extensions (edge://extensions in Edge)")
    print("  2. Turn on Developer mode")
    print("  3. Click Load unpacked and choose the folder above")
    print()
    print("After upgrading memty, run `memty extension` again and click reload on the extension.")
    print("The bridge must be running: memty serve --autostart (one time).")
    if args.open:
        extension.open_folder(result["path"])


def _clip(args, ledger) -> None:
    try:
        # Plain text is trimmed to --tokens after rendering; compile with headroom for it.
        budget = 1500 if args.format == "text" else args.tokens
        result = ledger.context(args.query, provider=args.provider, namespace=args.namespace,
                                token_budget=budget, strict_namespace=True)
    except LocalRoutingRequired as error:
        log_blocked(ledger, "clip", args.provider, namespace=args.namespace)
        _print(error.as_dict())
        raise SystemExit(2)
    text = result["text"]
    if not text:
        raise SystemExit(f"No facts to share in namespace '{args.namespace}'.")
    fact_ids = None
    if args.format == "text":  # chat assistants read labelled bullets better than XML slots
        text, included = render_plain_with_count(result, args.tokens)
        fact_ids = [item["id"] for item in result["citations"] if "id" in item][:included]
    log_served(ledger, "clip", args.provider, result, namespace=args.namespace,
               tokens=estimate_tokens(text), fact_ids=fact_ids,
               redacted=text.count("[private]") if args.format == "text" else None)
    if args.print_only:
        print(text)
        return
    from .integrations.clipboard import copy_text
    try:
        copy_text(text)
    except Exception as error:  # clipboard tool missing or failed: never lose the capsule
        print(text)
        raise SystemExit(f"Could not copy to the clipboard ({error}); the capsule is printed above.")
    redacted = len(result.get("redactions") or {})
    note = f", {redacted} confidential value(s) redacted" if redacted else ""
    print(f"Copied {args.namespace} capsule (~{estimate_tokens(text)} tokens{note}). Paste it into any AI.",
          file=sys.stderr)


def _scan_summary(scan: dict, applied: dict) -> str:
    files = ", ".join(scan["files"]) or "no manifests found"
    lines = [f"Scanned {len(scan['files'])} file(s) in {scan['elapsed_ms']:.1f} ms "
             f"(0 LLM tokens): {files}"]
    for error in scan["errors"]:
        lines.append(f"  ! could not parse {error['file']}: {error['error']}")
    verb = "would save" if applied["dry_run"] else "saved"
    counts = (f"{len(applied['saved'])} {verb}, {len(applied['updated'])} updated, "
              f"{len(applied['unchanged'])} unchanged")
    if applied["skipped"]:
        counts += f", {len(applied['skipped'])} kept as you set them"
    lines.append(f"{applied['namespace']}: {counts}")
    values = {item["slot"]: item["value"] for item in scan["facts"]}
    for mark, key in (("+", "saved"), ("~", "updated")):
        for slot in applied[key]:
            lines.append(f"  {mark} {slot} = {values[slot]}")
    for item in applied["skipped"]:
        reason = {"user_confirmed": "you confirmed a different value",
                  "deleted_by_user": "you deleted this slot"}.get(item["reason"], item["reason"])
        lines.append(f"  = {item['slot']} (unchanged: {reason})")
    if applied["stale"]:
        lines.append("  Not found in the project any more: " + ", ".join(applied["stale"])
                     + f" (remove with memty forget {applied['namespace']} <slot>)")
    if scan["facts"] and not applied["dry_run"]:
        lines.append(f'Recall it: memty recall "stack" --namespace {applied["namespace"]}')
    return "\n".join(lines)


def _scan(args, ledger) -> None:
    from .extraction.project_scan import apply_scan, scan_project
    try:
        scan = scan_project(args.path)
    except ValueError as error:
        raise SystemExit(str(error))
    applied = apply_scan(ledger, scan, args.namespace, dry_run=args.dry_run)
    if args.json:
        _print({**scan, **applied})
    else:
        print(_scan_summary(scan, applied))


def _resolve(args, ledger, approve: bool) -> None:
    ids = args.ids
    if args.all:
        ids = [item["id"] for item in ledger.proposals(status="PENDING", limit=1000)]
    if not ids:
        raise SystemExit("Nothing to do: pass proposal ids (see memty inbox) or --all.")
    failed = False
    for proposal_id in ids:
        try:
            result = ledger.resolve_proposal(proposal_id, approve=approve)
        except ValueError as error:
            print(f"[{proposal_id}] {error}", file=sys.stderr)
            failed = True
            continue
        if approve:
            print(f"[{proposal_id}] approved: {result['namespace']}.{result['slot']} = "
                  f"{json.dumps(result['value'], ensure_ascii=False)} (user-confirmed, v{result['version']})")
        else:
            print(f"[{proposal_id}] rejected: {result['namespace']}.{result['slot']} unchanged")
    if failed:
        raise SystemExit(1)


def main() -> None:
    if len(sys.argv) == 1:
        _welcome()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        from .runtime.daemon import main as daemon_main
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        daemon_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from .integrations.mcp.server import main as mcp_main
        mcp_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "vault":
        from .legacy.vault_cli import main as legacy_vault_main
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        legacy_vault_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        from .legacy.api import main as api_main
        api_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "vault-mcp":
        from .legacy.vault_mcp import main as legacy_mcp_main
        legacy_mcp_main()
        return
    parser = argparse.ArgumentParser(
        prog="memty",
        description="Memty: local-first, persistent memory for AI assistants",
        epilog="Also available: daemon, mcp; and for the older temporal vault: vault, api, vault-mcp.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    parser.add_argument("--db", default=str(default_vault_path()))
    parser.add_argument("--user", default=default_user_id())
    parser.add_argument("--trusted-provider", action="append", default=[],
                        help="Cloud provider allowed to see CONFIDENTIAL facts without redaction")
    commands = parser.add_subparsers(dest="command", required=True)

    remember = commands.add_parser("remember", help="save or supersede one atomic fact")
    remember.add_argument("namespace")
    remember.add_argument("slot")
    remember.add_argument("value")
    remember.add_argument("--confidence", type=float, default=1.0)
    remember.add_argument("--sensitivity", default="PUBLIC",
                          choices=["PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET"])
    remember.add_argument("--verification", default="USER_CONFIRMED",
                          choices=["USER_CONFIRMED", "SPEC_LOCKED", "EXTRACTED"])
    remember.add_argument("--allow-provider", action="append", default=[])
    remember.add_argument("--block-provider", action="append", default=[])
    remember.add_argument("--ephemeral-redaction", action="store_true")
    remember.add_argument("--raw", help="raw source text to archive for explicit drill-down")

    recall = commands.add_parser("recall", help="compile context within a token budget")
    recall.add_argument("query")
    recall.add_argument("--provider", default="local")
    recall.add_argument("--tokens", type=int, default=600)
    recall.add_argument("--namespace")

    forget = commands.add_parser("forget", help="tombstone a slot and purge its audit history")
    forget.add_argument("namespace")
    forget.add_argument("slot")
    forget.add_argument("--purge-raw", action="store_true")

    listing = commands.add_parser("list", help="list active facts")
    listing.add_argument("--namespace")
    listing.add_argument("--all", action="store_true", help="include tombstones")

    summary = commands.add_parser("summary", help="read or set a namespace summary")
    summary.add_argument("namespace")
    summary.add_argument("--set", dest="summary_text")
    summary.add_argument("--max-tokens", type=int, default=150)

    rule = commands.add_parser("rule", help="create or replace a logical namespace rule")
    rule.add_argument("namespace")
    rule.add_argument("rule_id")
    rule.add_argument("if_condition")
    rule.add_argument("then_constraint")

    rules = commands.add_parser("rules", help="list logical namespace rules")
    rules.add_argument("--namespace")

    rule_delete = commands.add_parser("rule-delete", help="delete a logical namespace rule")
    rule_delete.add_argument("namespace")
    rule_delete.add_argument("rule_id")

    commands.add_parser("stats", help="show vault counters and paths")
    connect = commands.add_parser(
        "connect", help="connect Memty to Claude, Codex, VS Code, Cursor, and Windsurf",
        description="Connect Memty through each client's own installer. Memty never writes client "
                    "settings files: supported CLIs install the server, Cursor shows its install "
                    "prompt, and Claude Desktop and Windsurf get exact manual steps.")
    connect.add_argument("--dry-run", action="store_true", help="show the plan without running anything")
    connect.add_argument("--no-open", action="store_true",
                         help="print the Cursor install link instead of opening it")
    connect.add_argument("--client", action="append", choices=["Claude Desktop", "Claude Code", "Codex CLI", "VS Code", "Cursor", "Windsurf"],
                         help="only connect this client (repeatable)")

    serve = commands.add_parser(
        "serve", help="run the localhost bridge for browser assistants (127.0.0.1 only)",
        description="Serve capsules to the Memty browser extension on 127.0.0.1. "
                    "Requests need the pairing token and an extension origin.")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allow-origin", action="append", default=[],
                       help="only accept this origin, e.g. chrome-extension://<id> (repeatable)")
    serve.add_argument("--background", action="store_true", help="start quietly in the background")
    serve.add_argument("--stop", action="store_true", help="stop a background bridge")
    serve.add_argument("--autostart", action="store_true",
                       help="start now and every time you log in (recommended, one-time setup)")
    serve.add_argument("--no-autostart", action="store_true", help="stop and remove the login autostart")
    serve.add_argument("--show-token", action="store_true", help="print the pairing token and exit")
    serve.add_argument("--new-token", action="store_true",
                       help="replace the pairing token and forget the paired extension (restart the bridge after)")
    serve.add_argument("--verbose", action="store_true", help="log request paths (never bodies)")

    pair = commands.add_parser("pair", help="connect another browser (or a reinstalled extension) to Memty")
    pair.add_argument("--port", type=int, default=8765)
    pair.add_argument("--seconds", type=int, default=120, help="how long pairing stays open")

    ext = commands.add_parser("extension", help="install the Memty Bridge browser extension folder")
    ext.add_argument("--dir", help="where to put it (default: ~/.memty/browser-extension)")
    ext.add_argument("--open", action="store_true", help="open the folder afterwards")

    clip = commands.add_parser("clip", help="copy a namespace capsule to the clipboard for any AI")
    clip.add_argument("namespace")
    clip.add_argument("--query", default="", help="rank facts for this question")
    clip.add_argument("--provider", default="clipboard",
                      help="who will read it; non-local providers get CONFIDENTIAL values redacted")
    clip.add_argument("--tokens", type=int, default=200)
    clip.add_argument("--format", choices=("text", "xml"), default="text",
                      help="text: plain Title: value lines for chat apps (default); xml: <memty_state> block")
    clip.add_argument("--print", dest="print_only", action="store_true",
                      help="print the capsule instead of copying it")

    raw_add = commands.add_parser("raw-add", help="archive raw text without changing facts")
    raw_add.add_argument("namespace")
    raw_add.add_argument("content")

    raw_get = commands.add_parser("raw-get", help="explicitly fetch an archived raw document")
    raw_get.add_argument("raw_id")

    history = commands.add_parser("history", help="show superseded versions for one slot")
    history.add_argument("namespace")
    history.add_argument("slot")

    migrate = commands.add_parser("migrate", help="import facts from a previous Memty temporal vault")
    migrate.add_argument("path")

    scan = commands.add_parser(
        "scan", aliases=["init"], help="bootstrap project facts from manifests (no model, no network)",
        description="Read pyproject.toml, package.json, Cargo.toml, Dockerfile and .env.example "
                    "(key names only) and save baseline facts as EXTRACTED. Facts you confirmed "
                    "or deleted are never changed.")
    scan.add_argument("path", nargs="?", default=".")
    scan.add_argument("--namespace", help="default: project.<folder name>")
    scan.add_argument("--dry-run", action="store_true", help="show what would be saved")
    scan.add_argument("--json", action="store_true")

    inbox = commands.add_parser("inbox", help="review facts proposed by connected agents")
    inbox.add_argument("--all", action="store_true", help="include approved, rejected and superseded")
    inbox.add_argument("--json", action="store_true")

    for name, verb in (("approve", "approve and save as user-confirmed"), ("reject", "reject")):
        resolve = commands.add_parser(name, help=f"{verb} inbox proposals")
        resolve.add_argument("ids", nargs="*", type=int)
        resolve.add_argument("--all", action="store_true", help=f"{name} every pending proposal")

    receipts = commands.add_parser("receipts", help="list recent context receipts (no values)")
    receipts.add_argument("--limit", type=int, default=20)
    receipts.add_argument("--json", action="store_true")

    report = commands.add_parser("report", help="summarize capsules served, facts reused and secrets protected")
    report.add_argument("--days", type=float, help="only the last N days")
    report.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "connect":
        from .integrations.mcp.connect import connect_clients
        results = connect_clients(dry_run=args.dry_run, clients=args.client,
                                  open_links=not args.no_open)
        _print(results)
        if any(item["status"] == "error" for item in results["clients"].values()):
            raise SystemExit(1)
        return
    if args.command == "serve":
        _serve(args)
        return
    if args.command == "extension":
        _extension(args)
        return
    if args.command == "pair":
        _pair(args)
        return
    ledger = _ledger(args)
    if args.command == "clip":
        _clip(args, ledger)
        return

    if args.command == "remember":
        result = ledger.record(
            args.namespace, args.slot, args.value, confidence=args.confidence,
            verification_state=args.verification, sensitivity=args.sensitivity,
            allowed_providers=args.allow_provider, blocked_providers=args.block_provider,
            ephemeral_redaction=args.ephemeral_redaction, source_raw=args.raw,
        )
        _print(result)
    elif args.command == "recall":
        try:
            result = ledger.context(args.query, provider=args.provider,
                                    token_budget=args.tokens, namespace=args.namespace)
        except LocalRoutingRequired as error:
            log_blocked(ledger, "recall", args.provider, namespace=args.namespace)
            _print(error.as_dict())
            raise SystemExit(2)
        log_served(ledger, "recall", args.provider, result, namespace=args.namespace)
        _print(result)
    elif args.command in {"scan", "init"}:
        _scan(args, ledger)
    elif args.command == "inbox":
        items = ledger.proposals(status=None if args.all else "PENDING", limit=1000)
        if args.json:
            _print(items)
        elif args.all:
            for item in items:
                print(f"[{item['id']}] {item['status']:<10} {item['namespace']}.{item['slot']} = "
                      f"{json.dumps(item['value'], ensure_ascii=False)} ({item['proposed_by']})")
            if not items:
                print("No proposals yet.")
        else:
            print(format_inbox(items))
    elif args.command in {"approve", "reject"}:
        _resolve(args, ledger, approve=args.command == "approve")
    elif args.command == "receipts":
        items = ledger.receipts(limit=args.limit)
        if args.json:
            _print(items)
        else:
            print(format_receipts(items))
    elif args.command == "report":
        since = None
        if args.days is not None:
            import time
            since = int((time.time() - args.days * 86400) * 1000)
        result = ledger.report(since_ms=since)
        if args.json:
            _print(result)
        else:
            print(format_report(result))
    elif args.command == "forget":
        result = ledger.forget(args.namespace, args.slot, purge_raw=args.purge_raw)
        if result is None:
            raise SystemExit("slot not found")
        _print(result)
    elif args.command == "list":
        _print(ledger.list(namespace=args.namespace, include_tombstones=args.all))
    elif args.command == "summary":
        if args.summary_text is not None:
            _print(ledger.set_summary(args.namespace, args.summary_text))
        elif ledger.summary(args.namespace) is not None:
            _print(ledger.summary(args.namespace))
        else:
            _print(ledger.summarize_namespace(args.namespace, max_tokens=args.max_tokens))
    elif args.command == "rule":
        _print(ledger.set_constraint(args.namespace, args.rule_id,
                                     args.if_condition, args.then_constraint))
    elif args.command == "rules":
        _print(ledger.list_constraints(namespace=args.namespace))
    elif args.command == "rule-delete":
        _print({"deleted": ledger.delete_constraint(args.namespace, args.rule_id),
                "namespace": args.namespace, "rule_id": args.rule_id})
    elif args.command == "stats":
        _print(ledger.stats())
    elif args.command == "raw-add":
        _print({"raw_id": ledger.archive_raw(args.namespace, args.content)})
    elif args.command == "raw-get":
        result = ledger.drill_down(args.raw_id)
        if result is None:
            raise SystemExit("raw document not found")
        _print(result)
    elif args.command == "history":
        _print(ledger.history(args.namespace, args.slot))
    elif args.command == "migrate":
        from .vault.migrate import migrate_from_legacy
        _print(migrate_from_legacy(args.path, ledger))
    else:  # pragma: no cover - argparse enforces the command list
        parser.error("unknown command")


if __name__ == "__main__":
    main()
