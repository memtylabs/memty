// Run with: node --test tests/test_memty_extension.cjs
// Set MEMTY_TEST_CHROME to the Chrome/Chromium executable if it is not on PATH.
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const contentScript = fs.readFileSync(path.join(__dirname, '../memty/integrations/browser/extension/content.js'), 'utf8');
const chromeCandidates = [process.env.MEMTY_TEST_CHROME,
  process.platform === 'win32' && 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  process.platform === 'darwin' && '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  'google-chrome', 'chromium', 'chromium-browser'].filter(Boolean);
const chrome = chromeCandidates.find((candidate) => {
  if (path.isAbsolute(candidate)) return fs.existsSync(candidate);
  const locator = process.platform === 'win32' ? 'where.exe' : 'which';
  return spawnSync(locator, [candidate], { stdio: 'ignore', windowsHide: true }).status === 0;
});
const WebSocketClient = globalThis.WebSocket || require('next/dist/compiled/ws');
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function until(read, condition, label) {
  const end = Date.now() + 10000;
  let last;
  while (Date.now() < end) {
    try { last = await read(); if (condition(last)) return last; } catch (error) { last = error.message; }
    await delay(50);
  }
  throw new Error(`Timed out waiting for ${label}: ${JSON.stringify(last)}`);
}

async function connect(url) {
  const socket = new WebSocketClient(url);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Chrome websocket connection timed out')), 5000);
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener('error', (error) => { clearTimeout(timer); reject(error); }, { once: true });
  });
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(String(event.data));
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    message.error ? reject(new Error(message.error.message)) : resolve(message.result);
  });
  return {
    send(method, params = {}) {
      const id = ++nextId;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`Chrome did not answer ${method}`));
        }, 5000);
        pending.set(id, {
          resolve: (value) => { clearTimeout(timer); resolve(value); },
          reject: (error) => { clearTimeout(timer); reject(error); },
        });
        socket.send(JSON.stringify({ id, method, params }));
      });
    },
    close() { socket.close(); },
  };
}

test('dragging and selected-text review work on a ChatGPT-style page',
  { skip: !chrome && 'Chrome or Chromium is required', timeout: 30000 }, async () => {
    const tempRoot = path.resolve(os.tmpdir());
    const profile = fs.mkdtempSync(path.join(tempRoot, 'memty-chrome-test-'));
    const page = http.createServer((request, response) => {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      response.end(`<!doctype html><style>
        #prompt-textarea { position:fixed; right:40px; bottom:20px; width:700px; height:70px; }
      </style><article id="answer"><p>The service uses a local vault. See <a href="https://example.com/docs">documentation</a>.</p><ul><li>Decision: Keep the cache local.</li>
        <li>Limit: 500 requests per minute.</li></ul><p>Never send private data to the cloud.</p></article>
        <div id="prompt-textarea" contenteditable="true" role="textbox"></div>`);
    });
    await new Promise((resolve) => page.listen(0, '127.0.0.1', resolve));
    const args = ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
      '--disable-background-networking', '--no-proxy-server', '--remote-debugging-port=0', '--remote-allow-origins=*',
      `--user-data-dir=${profile}`, 'about:blank'];
    if (process.platform === 'linux') args.unshift('--no-sandbox');
    const browser = spawn(chrome, args, { stdio: 'ignore', windowsHide: true });
    let client;
    try {
      const activePort = path.join(profile, 'DevToolsActivePort');
      const port = await until(() => fs.readFileSync(activePort, 'utf8').split(/\r?\n/)[0], Boolean, 'Chrome');
      const targets = await until(async () => (await fetch(`http://127.0.0.1:${port}/json/list`)).json(),
        (items) => items.some((item) => item.type === 'page'), 'browser target');
      client = await connect(targets.find((item) => item.type === 'page').webSocketDebuggerUrl);
      const send = client.send.bind(client);
      const evaluate = async (expression) => {
        const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
        if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
        return result.result.value;
      };
      await send('Emulation.setDeviceMetricsOverride', { width: 1200, height: 800, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url: `http://127.0.0.1:${page.address().port}/` });
      await until(() => evaluate('document.readyState'), (state) => state === 'complete', 'fixture page');
      const fixture = await evaluate(`({ url: location.href, editor: !!document.querySelector('#prompt-textarea'), title: document.title })`);
      assert.ok(fixture.editor, `fixture editor missing: ${JSON.stringify(fixture)}`);
      await evaluate(`
        window.__memtyStore = {};
        window.__memtyMessages = [];
        window.chrome = { runtime: { id: 'test', sendMessage: (message, cb) => {
          window.__memtyMessages.push(message);
          if (message.type === 'extract') return cb({ ok: true, result: {
            facts: [{slot: 'decision', value: 'Keep the cache local.'}], warnings: ['Review the split parts together.'] } });
          if (message.type === 'save') return cb({ ok: true, result: {
            namespace: 'project.api', saved: [{slot: 'decision'}], skipped: [] } });
          if (message.type === 'namespace-options') return cb({ok:true, result:{namespace:'repo.memty',
            namespaces:['personal', 'repo.memty'], detected:true}});
          if (message.type === 'contexts') return cb({ok: true, result: {contexts: [
            {id: 'recent', namespace: 'project.api', preview: 'Decision: New project', count: 2, updated_at: 2000},
            {id: 'older', namespace: 'another.project', preview: 'Decision: Old project', count: 2, updated_at: 1000}
          ]}});
          if (message.type === 'capsule' && window.__delayCapsule) { window.__pendingCapsule = cb; return; }
          cb({ ok: true, result: { text: '[Memty context]\\n1. Editor: VS Code\\n2. Platform: Local\\n[/Memty]',
            facts: 2, omitted: 2, namespace: message.namespace } });
        } }, storage: { local: {
          get: (key, cb) => setTimeout(() => cb({[key]: window.__memtyStore[key]}), 0),
          set: (value) => Object.assign(window.__memtyStore, value),
          remove: (key) => delete window.__memtyStore[key]
        } } };
        const realAttachShadow = Element.prototype.attachShadow;
        Element.prototype.attachShadow = function(init) {
          return realAttachShadow.call(this, this.dataset.memtyBridge ? {...init, mode: 'open'} : init);
        };
      `);
      const inject = () => evaluate(contentScript);
      const rect = () => evaluate(`(() => {
        const root = document.querySelector('[data-memty-bridge]')?.shadowRoot;
        const bar = root?.querySelector('.bar');
        const grip = root?.querySelector('.grip');
        if (!bar || bar.hidden) return null;
        const b = bar.getBoundingClientRect(), g = grip.getBoundingClientRect();
        return { x: b.left, y: b.top, width: b.width, height: b.height,
                 gripX: g.left + g.width / 2, gripY: g.top + g.height / 2,
                 touchAction: getComputedStyle(grip).touchAction };
      })()`);
      const mouse = (type, x, y, extra = {}) => send('Input.dispatchMouseEvent', { type, x, y, ...extra });
      const drag = async (dx, dy) => {
        const start = await rect();
        await mouse('mouseMoved', start.gripX, start.gripY);
        await mouse('mousePressed', start.gripX, start.gripY, { button: 'left', buttons: 1, clickCount: 1 });
        await mouse('mouseMoved', start.gripX + dx, start.gripY + dy, { button: 'left', buttons: 1 });
        await mouse('mouseReleased', start.gripX + dx, start.gripY + dy, { button: 'left', buttons: 0, clickCount: 1 });
        await delay(100);
        return rect();
      };

      await inject();
      const initial = await until(rect, Boolean, 'visible Memty pill');
      assert.equal(initial.touchAction, 'none');
      const moved = await drag(-300, -200);
      assert.ok(Math.abs(moved.x - (initial.x - 300)) <= 2, 'horizontal drag');
      assert.ok(Math.abs(moved.y - (initial.y - 200)) <= 2, 'vertical drag');
      await evaluate(`Object.assign(document.querySelector('#prompt-textarea').style,
        { right: '350px', bottom: '180px', height: '140px' })`);
      await delay(150);
      const afterComposerChange = await rect();
      assert.equal(afterComposerChange.x, moved.x);
      assert.equal(afterComposerChange.y, moved.y);
      assert.equal(await evaluate(`window.__memtyStore['memtyPos:127.0.0.1'].anchor`), 'viewport');

      await inject(); // extension reload: stored position must still be used
      const restored = await until(rect, Boolean, 'restored pill');
      assert.equal(restored.x, moved.x);
      assert.equal(restored.y, moved.y);
      await send('Emulation.setDeviceMetricsOverride', { width: 600, height: 400, deviceScaleFactor: 1, mobile: false });
      await delay(150);
      const resized = await rect();
      assert.ok(resized.x >= 0 && resized.x + resized.width <= 600);
      assert.ok(resized.y >= 0 && resized.y + resized.height <= 400);

      // At an edge, reversing direction should move immediately without a dead zone.
      const beforeEdge = await rect();
      await mouse('mouseMoved', beforeEdge.gripX, beforeEdge.gripY);
      await mouse('mousePressed', beforeEdge.gripX, beforeEdge.gripY, { button: 'left', buttons: 1, clickCount: 1 });
      await mouse('mouseMoved', 2, beforeEdge.gripY, { button: 'left', buttons: 1 });
      await delay(50);
      const edge = await rect();
      assert.equal(edge.x, 4);
      await mouse('mouseMoved', 47, beforeEdge.gripY, { button: 'left', buttons: 1 });
      await mouse('mouseReleased', 47, beforeEdge.gripY, { button: 'left', buttons: 0, clickCount: 1 });
      await delay(100);
      const reversed = await rect();
      assert.equal(reversed.x, 49);
      await mouse('mousePressed', reversed.gripX, reversed.gripY, { button: 'left', buttons: 1, clickCount: 1 });
      await mouse('mouseReleased', reversed.gripX, reversed.gripY, { button: 'left', buttons: 0, clickCount: 1 });
      await mouse('mousePressed', reversed.gripX, reversed.gripY, { button: 'left', buttons: 1, clickCount: 2 });
      await mouse('mouseReleased', reversed.gripX, reversed.gripY, { button: 'left', buttons: 0, clickCount: 2 });
      await delay(100);
      assert.equal(await evaluate(`'memtyPos:127.0.0.1' in window.__memtyStore`), false);

      // Positions from earlier extension versions remain usable after updating.
      await evaluate(`window.__memtyStore['memtyPos:127.0.0.1'] = {x: -40, y: -30}`);
      await inject();
      const legacy = await until(rect, Boolean, 'legacy position');
      const expected = await evaluate(`(() => {
        const editor = document.querySelector('#prompt-textarea').getBoundingClientRect();
        const bar = document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.bar').getBoundingClientRect();
        return { x: Math.round(Math.min(Math.max(4, editor.right - bar.width - 40), Math.max(4, innerWidth - bar.width - 4))),
                 y: Math.round(Math.min(Math.max(4, editor.top - bar.height - 8 - 30), Math.max(4, innerHeight - bar.height - 4))) };
      })()`);
      assert.equal(legacy.x, expected.x);
      assert.equal(legacy.y, expected.y);

      await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: legacy.gripX, y: legacy.gripY, id: 0 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: legacy.gripX + 60, y: legacy.gripY + 80, id: 0 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await delay(150);
      const touched = await rect();
      assert.ok(Math.abs(touched.x - (legacy.x + 60)) <= 2, 'touch moves horizontally');
      assert.ok(Math.abs(touched.y - (legacy.y + 80)) <= 2, 'touch moves vertically');
      assert.equal(await evaluate(`window.__memtyStore['memtyPos:127.0.0.1'].anchor`), 'viewport');

      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: touched.gripX, y: touched.gripY, id: 0 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: touched.gripX + 20, y: touched.gripY + 20, id: 0 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
      await send('Emulation.setTouchEmulationEnabled', { enabled: false });
      await delay(100);
      const afterCancel = await rect();
      const afterNextDrag = await drag(25, 15);
      assert.equal(afterNextDrag.x, afterCancel.x + 25, 'drag works after cancellation');
      assert.equal(afterNextDrag.y, afterCancel.y + 15, 'drag works after cancellation');

      const injectButton = await evaluate(`(() => {
        const b = document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.inject').getBoundingClientRect();
        return {x: b.left + b.width / 2, y: b.top + b.height / 2};
      })()`);
      await mouse('mouseMoved', injectButton.x, injectButton.y);
      await mouse('mousePressed', injectButton.x, injectButton.y, { button: 'left', buttons: 1, clickCount: 1 });
      await mouse('mouseReleased', injectButton.x, injectButton.y, { button: 'left', buttons: 0, clickCount: 1 });
      await until(() => evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelectorAll('.context-choice').length`),
        (count) => count === 2, 'context picker');
      const choices = await evaluate(`Array.from(document.querySelector('[data-memty-bridge]').shadowRoot
        .querySelectorAll('.context-choice'), (button) => button.textContent)`);
      assert.match(choices[0], /^1\. Decision: New project/);
      assert.match(choices[1], /^2\. Decision: Old project/);
      assert.equal(await evaluate(`window.__memtyMessages.filter((m) => m.type === 'capsule').length`), 0);
      await evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelectorAll('.context-choice')[1].click()`);
      await until(() => evaluate(`document.querySelector('#prompt-textarea').innerText`),
        (text) => text.includes('Editor: VS Code'), 'Memty button to insert a capsule');
      const chosen = await evaluate(`window.__memtyMessages.find((m) => m.type === 'capsule')`);
      assert.equal(chosen.context, 'older');
      assert.equal(chosen.namespace, 'another.project');
      const pasted = await evaluate(`document.querySelector('#prompt-textarea').innerText`);
      assert.match(pasted, /1\. Editor: VS Code/);
      assert.match(pasted, /2\. Platform: Local/);
      assert.doesNotMatch(pasted, /New project/);
      assert.match(await evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.toast').textContent`),
        /2 not included/);

      await evaluate(`window.__delayCapsule = true;
        document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.inject').click()`);
      await until(() => evaluate(`!document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.card').hidden`),
        Boolean, 'context picker again');
      const beforeCancel = await evaluate(`document.querySelector('#prompt-textarea').innerText`);
      await evaluate(`(() => { const buttons = document.querySelector('[data-memty-bridge]').shadowRoot
        .querySelectorAll('.context-choice'); buttons[0].click(); buttons[1].click(); })()`);
      assert.equal(await evaluate(`window.__memtyMessages.filter((m) => m.type === 'capsule').length`), 2);
      await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
        window.__pendingCapsule({ok:true, result:{text:'[Memty context]\\n1. Wrong: unwanted\\n[/Memty]',
          facts:1, omitted:0, namespace:'project.api'}}); window.__delayCapsule = false;`);
      await delay(100);
      assert.equal(await evaluate(`document.querySelector('#prompt-textarea').innerText`), beforeCancel);

      await evaluate(`(() => { const range = document.createRange();
        range.selectNodeContents(document.querySelector('#answer'));
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); })()`);
      await until(() => evaluate(`!document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.bubble').hidden`),
        Boolean, 'save selection button');
      const bubble = await evaluate(`(() => { const r = document.querySelector('[data-memty-bridge]').shadowRoot
        .querySelector('.bubble').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
      await mouse('mouseMoved', bubble.x, bubble.y);
      await mouse('mousePressed', bubble.x, bubble.y, { button: 'left', buttons: 1, clickCount: 1 });
      await mouse('mouseReleased', bubble.x, bubble.y, { button: 'left', buttons: 0, clickCount: 1 });
      await until(() => evaluate(`!document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.card').hidden`),
        Boolean, 'fact review');
      const selection = await evaluate(`window.__memtyMessages.find((m) => m.type === 'extract').text`);
      assert.match(selection, /The service uses a local vault/);
      assert.match(selection, /documentation \(https:\/\/example\.com\/docs\)/);
      assert.match(selection, /- Decision: Keep the cache local/);
      assert.match(selection, /- Limit: 500 requests per minute/);
      assert.match(selection, /Never send private data to the cloud/);
      assert.match(await evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.review-note').textContent`),
        /Review the split parts/);
      assert.equal(await evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.source pre').textContent`), selection);
      assert.equal(await evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.project select').value`), 'repo.memty');
      await evaluate(`(() => { const project = document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.project');
        const select = project.querySelector('select'); select.value = '__new__'; select.dispatchEvent(new Event('change'));
        project.querySelector('input').value = 'project.api'; })()`);
      await evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.card .primary').click()`);
      const saved = await until(() => evaluate(`window.__memtyMessages.find((m) => m.type === 'save')`),
        Boolean, 'reviewed facts to save');
      assert.deepEqual(saved.facts, [{ slot: 'decision', value: 'Keep the cache local.' }]);
      assert.equal(saved.namespace, 'project.api');

      await evaluate(`(() => { const answer = document.querySelector('#answer'); answer.textContent = 'word '.repeat(10001);
        const range = document.createRange(); range.selectNodeContents(answer);
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
        document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.save').click(); })()`);
      await until(() => evaluate(`document.querySelector('[data-memty-bridge]').shadowRoot.querySelector('.toast').textContent`),
        (text) => text.includes('too long'), 'oversized selection warning');
      assert.equal(await evaluate(`window.__memtyMessages.filter((m) => m.type === 'extract').length`), 1);
    } finally {
      if (client) client.close();
      browser.kill();
      if (browser.exitCode === null) await Promise.race([new Promise((resolve) => browser.once('exit', resolve)), delay(3000)]);
      page.closeAllConnections();
      await new Promise((resolve) => page.close(resolve));
      // Only remove the temporary profile created by this test.
      if (path.dirname(path.resolve(profile)) === tempRoot && path.basename(profile).startsWith('memty-chrome-test-')) {
        fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
      }
    }
  });
