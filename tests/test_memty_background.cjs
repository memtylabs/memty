const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('browser saves create separate contexts and retrieval selects one namespace and context', async () => {
  const requests = [];
  const settings = { port: 8765, token: 'test-token', namespace: 'work.project' };
  const chrome = {
    storage: { local: { get: async () => settings, set: async (value) => Object.assign(settings, value), remove: async () => {} } },
    runtime: { onMessage: { addListener() {} }, onInstalled: { addListener() {} } },
    action: { onClicked: { addListener() {} } },
  };
  const context = vm.createContext({ chrome, URL, URLSearchParams, AbortSignal,
    fetch: async (url, options) => {
      requests.push({ url, options });
      const pathname = new URL(url).pathname;
      const body = pathname === '/namespaces' ? { namespaces: ['work.project', 'repo.memty', 'project.api'] }
        : pathname === '/facts' ? { saved: [{slot: 'decision'}] }
        : pathname === '/capsule' ? { text: 'selected context' } : {};
      return { ok: true, status: 200, json: async () => body };
    } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../memty/integrations/browser/extension/background.js'), 'utf8'), context);
  const sender = { url: 'https://chatgpt.com/c/test' };
  const detected = await context.handle({ type: 'namespace-options', hint: 'The repo.memty project uses MCP.' }, sender);
  assert.equal(detected.namespace, 'repo.memty');
  assert.equal(detected.detected, true);
  assert.equal(settings.namespace, 'work.project'); // a suggestion does not change the active project
  const ambiguous = await context.handle({ type: 'namespace-options', hint: 'Compare repo.memty with project.api.' }, sender);
  assert.equal(ambiguous.namespace, 'work.project');
  const newProject = await context.handle({ type: 'namespace-options', hint: 'Continue project.new_app.' }, sender);
  assert.equal(newProject.namespace, 'project.new_app');

  await context.handle({ type: 'save', namespace: 'repo.memty', facts: [{ slot: 'decision', value: 'Keep it local' }] }, sender);
  const saved = JSON.parse(requests.at(-1).options.body);
  assert.equal(saved.namespace, 'repo.memty');
  assert.equal(saved.confirmed, true);
  assert.equal(saved.separate_context, true);
  assert.equal(settings.namespace, 'repo.memty');
  await assert.rejects(context.handle({ type: 'save', namespace: 'bad name', facts: [] }, sender), /namespace/);

  await context.handle({ type: 'contexts' }, sender);
  const listing = new URL(requests.at(-1).url);
  assert.equal(listing.pathname, '/contexts');
  assert.equal(listing.searchParams.get('provider'), 'openai');

  await context.handle({ type: 'capsule', namespace: 'another.project', context: 'save_example' }, sender);
  const capsule = new URL(requests.at(-1).url);
  assert.equal(capsule.pathname, '/capsule');
  assert.equal(capsule.searchParams.get('namespace'), 'another.project');
  assert.equal(capsule.searchParams.get('context'), 'save_example');
  assert.equal(capsule.searchParams.get('provider'), 'openai');
  assert.equal(capsule.searchParams.get('tokens'), '2000');
  assert.equal(settings.namespace, 'another.project');
});
