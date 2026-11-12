# Memty Bridge (browser extension)

Use your local Memty vault in Perplexity, ChatGPT, Claude.ai, and Gemini. The extension adds a purple **⋮⋮ ⚡ Memty | ＋ Save** pill just above the prompt box. Drag the **⋮⋮** grip to move the pill anywhere on the page. Each site remembers its own position, even when the prompt box changes size. Double-click the grip to reset it.

- **⚡ Memty** or **Alt+M** opens your saved contexts, newest first. Choose one to add its numbered facts to the prompt, where you can check and edit them before sending:

  ```
  [Memty context]
  1. Company: MEMTY
  2. Category: Portable AI Memory Infrastructure
  3. Client: [private]
  [/Memty]
  ```

- **Select any text** in an answer and a **＋ Save to Memty** bubble appears above it. **＋ Save** on the pill does the same for your selection, or for the latest answer if nothing is selected. Memty proposes facts on your machine. Compare them with the original text in the review panel, then edit or untick them before saving. Each save becomes its own context, even when another context has facts with the same titles. Long passages may be split into related parts; the panel warns when a limit leaves content out.
  - Headings, questions, and Memty blocks you pasted earlier are ignored.
  - Bare file paths are combined into one `files` fact.
  - Code is never saved. Each code block becomes one summary fact, for example `JavaScript code in content.js defines injectCapsule, saveFacts`.
  - A chat capsule has a size limit and may include only some saved facts. Memty reports when facts were left out because of space or privacy settings.

## Install (one time)

1. In a terminal, run `memty daemon` to start the shared vault daemon and browser bridge. To also start the bridge at login, run `memty serve --autostart`; undo that with `memty serve --no-autostart`.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and choose the folder that `memty extension` prints.

That's all. There's no token to copy and no settings to fill in:

- The extension pairs itself with the bridge the first time you use it.
- When reviewing a selection, Memty suggests an explicitly mentioned project namespace, such as `repo.memty`, when it can identify one. Choose a different namespace or create one in the review panel. Your last chosen namespace is remembered; if none is selected, Memty defaults to the namespace with the most facts, or `personal` for an empty vault. Suggestions use text matching and should be checked before saving.
- After you update or reload the extension, open chat tabs get the new version automatically, with no page refresh.

Edge and Brave work the same way, through their extensions pages.

## Your facts, under your control

Click **☰** on the pill, or the extension icon, to open **Your Memty facts**. There you can:

- view every fact in a namespace, newest first
- edit a fact's title or value, or add a new fact
- mark a fact **Private**: chat AIs only see `[private]`, and the value is never shown in the browser
- delete a fact: Memty forgets it completely, including its history, and saving from a chat can't bring it back

## Privacy and security

- The bridge only listens on `127.0.0.1`. It refuses requests from web pages, and every data request needs the pairing token.
- Pairing is trust on first use. The first browser extension that asks the bridge for the token is remembered, and every other extension and every web page is refused. To connect another browser, or an extension you reinstalled, run `memty pair` and click **Try again**.
- Only the extension's background worker holds the token. The scripts that run inside chat sites never see it.
- Each site counts as a cloud provider (`perplexity`, `openai`, `anthropic`, `google`). The extension derives the provider from the tab's real URL. CONFIDENTIAL values are redacted, and a selected context containing an eligible SECRET fact is refused.
- Reviewed browser saves are stored as confirmed facts in a new context. Editing or deleting a fact changes only that fact. Automated extraction without confirmation cannot overwrite confirmed facts or restore deleted slots.
- To use a local model for extraction, set `MEMTY_OLLAMA_MODEL` (for example `llama3.1`) before running `memty serve`. If Ollama doesn't respond, Memty falls back to heuristics.
- To pin the bridge to your extension's ID, use `memty serve --allow-origin chrome-extension://<id>`.
- To revoke access, run `memty serve --new-token`. This also forgets the paired extension.

## Known limits

- Chat sites change their page structure often. The prompt-box and answer selectors in `content.js` are best effort. If **＋ Save** can't find the answer, select the text you want instead.
- Older facts that were saved without context information appear individually. Facts overwritten before context separation cannot be reconstructed as a complete past selection.
- To stop the bridge, run `memty serve --stop`.

## Development check

Run `npm run test:extension` from the repository root to test dragging, prompt insertion, and selected-text review in headless Chrome against a local ChatGPT-style page. Set `MEMTY_TEST_CHROME` to the browser executable if Chrome or Chromium is not on your PATH.
