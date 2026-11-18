# Use Memty in your browser

The bundled Memty Bridge extension supports ChatGPT, Claude.ai, Gemini, and Perplexity in Chromium-based browsers such as Chrome, Edge, and Brave.

## Install and connect

1. Install Memty using [Getting started](getting-started.md).
2. Start the local bridge and set it to start at login:

   ```sh
   memty serve --autostart
   memty extension --open
   ```

3. Open `chrome://extensions`, `edge://extensions`, or your browser's extensions page. Enable Developer mode, choose **Load unpacked**, and select the extension folder opened by Memty.
4. Open a supported chat site. The extension normally pairs automatically. To connect a second browser or a reinstalled extension, run `memty pair`, then retry within the pairing window.

Pairing trusts the first extension that connects; install the extension from your own Memty package before pairing. See [privacy](privacy.md).

## Save and reuse memory

Select text in a chat and choose **Save to Memty**, or use **Save** on the Memty pill. Check the suggested namespace and every proposed fact; edit or untick anything you do not want, then save. Each reviewed save forms a context.

Choose **Memty** on the pill or press `Alt+M`, select a context, and inspect the text inserted into the prompt before sending. Size and privacy limits can leave facts out. Drag the pill by its grip to move it; double-click the grip to reset its position.

Open **Your Memty facts** using the pill's menu or the extension icon. Select a namespace to search, add, edit, mark private, or delete facts. The **Delete all** action for the selected namespace is planned for 0.2.2. It includes private and search-hidden facts and cannot be undone; other namespaces are not selected by that action.

## Updates and controls

After upgrading the package, run `memty extension` again and reload the extension from the browser's extensions page. `memty serve --stop` stops a background bridge. `memty serve --no-autostart` removes login startup and stops it. To revoke pairing, run `memty serve --new-token` and restart the bridge; pair trusted extensions again.

The browser's fact deletion does not request a raw-source purge. Archived sources, backups, and copies sent to an AI service may remain. See [privacy and deletion](privacy.md). If the pill or connection is missing, see [troubleshooting](troubleshooting.md).
