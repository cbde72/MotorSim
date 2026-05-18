(function () {
  const mount = document.getElementById('app');
  const data = window.THERMO0D_DOC_DATA || {version: 4, sections: [], exampleYaml: ''};
  if (!mount) return;

  const esc = (s) => String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  const sectionCards = (data.sections || []).map((section, idx) => `
    <section class="panel-card p-4 xl:p-5" id="doc-section-${idx}">
      <div class="text-[11px] uppercase tracking-[0.18em] text-accent">Abschnitt</div>
      <h3 class="text-lg font-semibold mt-1.5">${esc(section.title || 'Ohne Titel')}</h3>
      <p class="text-sm text-muted mt-3 leading-6">${esc(section.body || '')}</p>
    </section>
  `).join('');

  mount.innerHTML = `
    <section id="toolbar" class="panel-card p-4 xl:p-5 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-[11px] uppercase tracking-[0.22em] text-accent">Browser-Editor</div>
          <h2 class="text-lg xl:text-xl font-semibold mt-1.5">Installationsfreie YAML-Vorschau</h2>
        </div>
        <div class="rounded-full border border-line2 bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent">Schema v${esc(data.version)}</div>
      </div>
      <div class="grid gap-4 xl:grid-cols-2">
        <div class="space-y-3">
          <label class="text-sm font-medium">Beispiel-YAML</label>
          <textarea id="yaml-editor" class="w-full min-h-[340px] rounded-2xl border border-line bg-panel2 px-4 py-3 font-mono text-sm outline-none" spellcheck="false">${esc(data.exampleYaml || '')}</textarea>
        </div>
        <div class="space-y-3">
          <label class="text-sm font-medium">Vorschau</label>
          <pre id="yaml-preview" class="min-h-[340px] overflow-auto rounded-2xl border border-line bg-panel2 px-4 py-3 text-sm leading-6 text-text"></pre>
        </div>
      </div>
      <div class="flex flex-wrap gap-3">
        <button id="btn-format" class="rounded-2xl border border-line2 bg-accent/10 px-4 py-2 text-sm font-medium text-accent">Vorschau aktualisieren</button>
        <button id="btn-download" class="rounded-2xl border border-line2 bg-panel2 px-4 py-2 text-sm font-medium">YAML exportieren</button>
      </div>
    </section>
    <div class="mt-4 grid gap-4">${sectionCards}</div>
  `;

  const editor = document.getElementById('yaml-editor');
  const preview = document.getElementById('yaml-preview');
  const render = () => {
    preview.textContent = editor.value || '';
    const title = document.getElementById('formula-title');
    const body = document.getElementById('formula-body');
    if (title) title.textContent = 'YAML-Vorschau';
    if (body) body.innerHTML = '<p class="text-sm text-muted leading-6">Die rechte Vorschau zeigt den aktuellen Textstand der YAML-Datei. Über „YAML exportieren“ wird der aktuelle Inhalt lokal als Datei gespeichert.</p>';
  };

  document.getElementById('btn-format')?.addEventListener('click', render);
  document.getElementById('btn-download')?.addEventListener('click', () => {
    const blob = new Blob([editor.value || ''], { type: 'text/yaml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'thermo0d_config.yaml';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  editor?.addEventListener('input', render);
  render();
})();
