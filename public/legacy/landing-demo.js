(() => {
  const root = document.querySelector('[data-legacy-page="landing"] [data-session-demo]');
  if (!root || root.dataset.ready) return;
  root.dataset.ready = 'true';

  const title = root.querySelector('[data-demo-title]');
  const copy = root.querySelector('[data-demo-copy]');
  const code = root.querySelector('[data-demo-code]');
  const output = root.querySelector('[data-demo-output]');
  const tabs = [...document.querySelectorAll('.demo-scenes article')];
  const controls = document.createElement('div');
  controls.className = 'demo-controls';
  controls.innerHTML = '<div class="demo-control-actions"><button class="demo-control-button" type="button" data-demo-action="pause" aria-pressed="false">Pause</button><span class="demo-stage-status" aria-live="polite">Step 1 of 5</span></div>';
  root.after(controls);

  const pauseButton = controls.querySelector('[data-demo-action="pause"]');
  const status = controls.querySelector('.demo-stage-status');
  const steps = [
    {
      title: '1. Install Memty',
      copy: 'One Python package: the local vault, the memtyd daemon, the MCP server, and the browser extension. Nothing leaves your computer until you send a chat.',
      code: 'python -m pip install memty\nmemty extension',
      output: ['memty installed', 'Memty Bridge is ready in ~/.memty/browser-extension']
    },
    {
      title: '2. Bootstrap a project',
      copy: 'Run it once in a code folder. Memty reads the manifests and saves baseline facts with no model and no tokens; env templates contribute key names only.',
      code: 'cd ~/code/billing-api\nmemty scan',
      output: ['Scanned 4 file(s) in 3.1 ms (0 LLM tokens)', 'project.billing-api: 14 saved, 0 updated, 0 unchanged']
    },
    {
      title: '3. Connect your agents',
      copy: 'Each client installs Memty through its own official installer. Every agent then talks to the same daemon and the same vault.',
      code: 'memty connect',
      output: ['Claude Code: connected', 'Cursor: install prompt opened', 'Codex CLI: connected']
    },
    {
      title: '4. Remember once, recall anywhere',
      copy: 'Save a fact from any client. The next assistant gets a capsule of only the relevant facts, filtered by the privacy gate for that provider.',
      code: 'memty remember work.preferences editor "VS Code"\nmemty recall "Which editor do I use?" --namespace work.preferences',
      output: ['<memty_state v="1" provider="local">', 'work.preferences.editor="VS Code"', '</memty_state>']
    },
    {
      title: '5. Stay in control',
      copy: 'Agents propose changes instead of overwriting your facts, and every capsule served leaves a receipt with counts and slot names, never values.',
      code: 'memty inbox\nmemty approve 1\nmemty report',
      output: ['[1] project.api -> cache_engine: "Redis" => "DragonflyDB" (Proposed by Cursor)',
               'Capsules served, verified facts reused, tokens saved, SECRET slots protected']
    }
  ];

  let runId = 0;
  let paused = false;
  let visible = true;
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async (ms, id) => {
    let remaining = ms;
    while (remaining > 0 && id === runId) {
      if (paused || !visible) { await delay(100); continue; }
      const slice = Math.min(50, remaining);
      await delay(slice);
      remaining -= slice;
    }
    return id === runId;
  };

  const typeCode = async (value, id) => {
    if (!code) return;
    code.textContent = '';
    for (const character of value) {
      if (!(await wait(28, id))) return;
      code.textContent += character;
    }
  };

  const play = async (index = 0) => {
    const id = ++runId;
    const stepIndex = (index + steps.length) % steps.length;
    const step = steps[stepIndex];
    tabs.forEach((tab, i) => {
      tab.classList.toggle('active', i === stepIndex);
      tab.setAttribute('aria-selected', String(i === stepIndex));
    });
    if (title) title.textContent = step.title;
    if (copy) copy.textContent = step.copy;
    if (output) output.replaceChildren();
    if (code) code.textContent = '';
    if (status) status.textContent = `Step ${stepIndex + 1} of ${steps.length} - Writing example`;

    if (!(await wait(700, id))) return;
    await typeCode(step.code, id);
    if (id !== runId) return;
    if (status) status.textContent = `Step ${stepIndex + 1} of ${steps.length} - Running example`;
    for (const line of step.output) {
      if (!(await wait(700, id))) return;
      const row = document.createElement('div');
      row.className = 'demo-output-line';
      row.textContent = line;
      if (output) output.append(row);
    }
    if (status) status.textContent = `Step ${stepIndex + 1} of ${steps.length} - Complete`;
    if (await wait(3200, id)) void play(stepIndex + 1);
  };

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const selectStep = index => {
    if (!reducedMotion) {
      paused = false;
      if (pauseButton) { pauseButton.textContent = 'Pause'; pauseButton.setAttribute('aria-pressed', 'false'); }
      void play(index);
      return;
    }
    const step = steps[index];
    ++runId;
    tabs.forEach((tab, i) => { tab.classList.toggle('active', i === index); tab.setAttribute('aria-selected', String(i === index)); });
    if (title) title.textContent = step.title;
    if (copy) copy.textContent = step.copy;
    if (code) code.textContent = step.code;
    if (output) output.replaceChildren(...step.output.map(line => {
      const row = document.createElement('div');
      row.className = 'demo-output-line';
      row.textContent = line;
      return row;
    }));
    if (status) status.textContent = `Step ${index + 1} of ${steps.length} - Complete`;
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectStep(index));
    tab.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectStep(index); }
    });
  });
  const replayButton = root.querySelector('[data-demo-action="replay"]');
  if (replayButton) replayButton.addEventListener('click', () => selectStep(0));
  if (pauseButton) pauseButton.addEventListener('click', () => {
    paused = !paused;
    pauseButton.textContent = paused ? 'Resume' : 'Pause';
    pauseButton.setAttribute('aria-pressed', String(paused));
  });
  const observer = new IntersectionObserver(entries => { visible = entries[0] ? entries[0].isIntersecting : true; });
  observer.observe(root);
  if (reducedMotion) selectStep(0);
  else void play(0);
})();
