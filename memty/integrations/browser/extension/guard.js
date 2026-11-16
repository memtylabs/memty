// Memty Bridge keyboard guard. Runs at document_start, before any page script.
// Chat sites (ChatGPT, Claude.ai, Gemini) listen for keys on window/document and
// move focus to their prompt box when you type outside a text field. Memty's
// panel lives in a closed shadow root, so to the page every key typed into a
// fact title or text looks like it came from a plain <div>, and the keystrokes
// were sent to the chat box instead. Listening on window in the capture phase,
// registered before the page's own listeners, lets us stop those events from
// reaching the page. The browser still inserts the text: nothing is cancelled.
(() => {
  if (window.__memtyKeyGuard) return; // already installed in this frame
  window.__memtyKeyGuard = true;
  const TYPES = ["keydown", "keypress", "keyup", "beforeinput", "input", "textInput",
                 "paste", "cut", "copy", "compositionstart", "compositionupdate", "compositionend"];
  const guard = (event) => {
    // Events from inside the shadow root are retargeted to its host element.
    if (!event.target?.dataset?.memtyBridge) return;
    if (event.type === "keydown" && event.key === "Escape") return; // content.js closes the panel
    event.stopImmediatePropagation();
  };
  for (const type of TYPES) window.addEventListener(type, guard, true);
})();
