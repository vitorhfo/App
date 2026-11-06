let currentProjectId = null;
let currentProjectData = null;
let projectDetailsLoadSequence = 0;
let materialSaveInFlight = false;
window.budgetUiState = {view: 'view-projetos', project: null, projects: []};
let currentProjectPdfs = [];
let aiPdfReviews = new Map();
let aiPdfModels = new Map();
let aiPdfJobs = [];
let aiPausedUntilByModel = {};
let aiPdfExpanded = new Set();
let aiJobTimer = null;
let aiPendingBusy = false;
const aiPdfBusy = new Set();
const aiDefaultModel = 'auto';
const aiAutoModels = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'];

function aiReviewKey(path, model) { return `${model}\u0000${path}`; }
let joseSourceFolders = [];

function html(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function sourceLink(ref) {
  if (!ref || !ref.includes('#page=')) return html(ref || '-');
  const [path, page] = ref.split('#page=');
  return `<a href="/api/projects/${currentProjectId}/source?path=${encodeURIComponent(path)}#page=${encodeURIComponent(page)}" target="_blank">${html(path.split('/').pop())}:p${html(page)}</a>`;
}

document.addEventListener("DOMContentLoaded", () => {
  loadProjectsList();
  loadRulesList();
  loadJoseSourceFolders();
});

async function loadJoseSourceFolders() {
  try {
    const res = await fetch('/api/source-folders/jose-vitor');
    if (!res.ok) return;
    joseSourceFolders = await res.json();
    const options = joseSourceFolders.map(f =>
      `<option value="${html(f.path)}">${html(f.client)} / ${html(f.name)}</option>`).join('');
    document.getElementById('np-jose-folder').insertAdjacentHTML('beforeend', options);
    document.getElementById('jose-source-folders').innerHTML = options;
  } catch (error) {
    console.warn('Não foi possível listar as pastas de José Vitor.', error);
  }
}

function chooseJoseFolder(path) {
  if (!path) return;
  const folder = joseSourceFolders.find(f => f.path === path);
  if (!folder) return;
  document.getElementById('np-folder').value = folder.path;
  document.getElementById('np-name').value = folder.name;
  document.getElementById('np-client').value = folder.client;
}

// Navegação entre Telas
function switchView(viewId) {
  document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));

  const target = document.getElementById(viewId);
  if (!target) return;
  target.classList.add("active");
  window.budgetUiState.view = viewId;
  window.dispatchEvent(new CustomEvent('budget:view', {detail: viewId}));

  if (viewId === "view-projetos") {
    loadProjectsList();
  } else if (viewId === "view-regras") {
    loadRulesList();
  } else if (currentProjectId) {
    loadProjectDetails(currentProjectId);
  }
}

// Modal Helpers
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("active");
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("active");
}

function openNewProjectModal() {
  document.getElementById("np-name").value = "";
  document.getElementById("np-code").value = "";
  document.getElementById("np-client").value = "HH GLOBAL";
  document.getElementById("np-folder").value = "";
  document.getElementById("np-jose-folder").value = "";
  document.getElementById("np-notes").value = "";
  openModal("modal-new-project");
}

// 1. PROJETOS
async function loadProjectsList() {
  try {
    const res = await fetch("/api/projects");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    window.budgetUiState.projects = data;
    window.dispatchEvent(new CustomEvent('budget:projects', {detail: data}));
  } catch (err) {
    console.error("Erro ao listar projetos:", err);
    window.dispatchEvent(new CustomEvent('budget:projects-error', {detail: err.message}));
  }
}

async function submitNewProject() {
  const name = document.getElementById("np-name").value.trim();
  if (!name) return alert("Por favor informe o nome do projeto.");

  const payload = {
    name: name,
    code: document.getElementById("np-code").value.trim(),
    client: document.getElementById("np-client").value.trim(),
    folder_path: document.getElementById("np-folder").value.trim(),
    notes: document.getElementById("np-notes").value.trim()
  };

  const res = await fetch("/api/projects", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!res.ok) return alert(data.detail || 'Não foi possível criar o projeto.');
  closeModal("modal-new-project");
  
  if (payload.folder_path) {
    // Se informou pasta, importar de imediato
    const imported = await fetch(`/api/projects/${data.id}/import-folder`, {
      method: "POST",
      body: new URLSearchParams({folder_path: payload.folder_path})
    });
    if (!imported.ok) alert((await imported.json()).detail || 'Projeto criado, mas a pasta não foi importada.');
  }

  selectProject(data.id);
}

async function seedHistoricalData(button) {
  const btn = button || window.event?.target;
  if (!btn) return;
  btn.disabled = true;
  btn.innerText = "⏳ Importando 3 projetos...";
  try {
    const res = await fetch("/api/seed-historical", {method: "POST"});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha na importação dos exemplos.');
    alert(data.imported.length ? "Projetos importados:\n- " + data.imported.map(x => `${x.name} (${x.items} itens)`).join("\n- ") : 'Os três projetos de exemplo já estavam carregados.');
    loadProjectsList();
  } catch (e) {
    alert("Erro ao importar: " + e.message);
  } finally {
    btn.disabled = false;
    btn.innerText = "⚡ Carregar 3 Exemplos de 'DADOS'";
  }
}

// SELECIONAR PROJETO
async function selectProject(id) {
  currentProjectId = id;
  await loadProjectDetails(id);
  switchView("view-bom");
}

async function loadProjectDetails(id) {
  const requestSequence = ++projectDetailsLoadSequence;
  try {
    const res = await fetch(`/api/projects/${id}`);
    if (!res.ok) throw new Error("Falha ao buscar projeto");
    const projectData = await res.json();
    // Several views can request a refresh at once. Ignore an older response
    // so it cannot repaint the table with a snapshot taken before a save.
    if (requestSequence !== projectDetailsLoadSequence || currentProjectId !== id) return;
    currentProjectData = projectData;

    // Atualizar Cabeçalho
    const p = currentProjectData.project;
    window.budgetUiState.project = p;
    window.dispatchEvent(new CustomEvent('budget:project', {detail: p}));

    if (p.folder_path) {
      document.getElementById("import-folder-input").value = p.folder_path;
    }

    renderMaterialsTable();
    renderReadingReport();
    renderWireVariants();
    renderAiDiscoveredItems();
    renderAssemblyTree();
    renderWeightView();
    renderMarkupView();
    renderPendingView();
    renderFinalView();
    loadProjectPdfs(id);
    refreshAiPendingDimensions(id);
    if (document.querySelector('.view-panel.active')?.id?.startsWith('view-orc-')) {
      loadQuoteViews(id);
    }
  } catch (err) {
    console.error("Erro ao carregar detalhes:", err);
  }
}

function renderReadingReport() {
  const target = document.getElementById('reading-report-content');
  if (!target) return;
  target.replaceChildren();
  const report = currentProjectData?.reading_report;
  if (!report?.events?.length) {
    target.textContent = 'Este projeto ainda não tem registro de leitura. O registro será criado na próxima importação.';
    return;
  }
  const notice = document.createElement('p');
  notice.textContent = 'Registro da última importação. As medidas e quantidades pendentes ainda precisam de conferência nos desenhos. Edições posteriores aparecem na lista de materiais.';
  target.appendChild(notice);
  const stages = {selected: 'Lista usada como principal', recognized: 'Lista reconhecida',
                  error: 'Falha de leitura', unresolved: 'Composição pendente'};
  const list = document.createElement('ul');
  for (const event of report.events) {
    const item = document.createElement('li');
    const heading = document.createElement('strong');
    heading.textContent = `${stages[event.stage] || 'Leitura'}: ${event.label}`;
    item.appendChild(heading);
    const detail = document.createElement('p');
    detail.textContent = `${event.source_page} · ${event.rows} linha(s). ${event.reason || ''}`;
    item.appendChild(detail);
    list.appendChild(item);
  }
  target.appendChild(list);
}

async function loadProjectPdfs(projectId) {
  const target = document.getElementById('project-pdfs-list');
  if (!target) return;
  currentProjectPdfs = [];
  aiPdfReviews = new Map();
  aiPdfModels = new Map();
  aiPdfJobs = [];
  aiPausedUntilByModel = {};
  aiPdfExpanded = new Set();
  if (aiJobTimer) clearTimeout(aiJobTimer);
  aiJobTimer = null;
  target.textContent = 'Carregando PDFs do projeto...';
  document.getElementById('project-pdfs-count').textContent = '…';
  document.getElementById('project-pdfs-warning').textContent = '';
  try {
    const response = await fetch(`/api/projects/${projectId}/pdfs`);
    if (!response.ok) throw new Error('Não foi possível listar os PDFs.');
    const files = await response.json();
    if (currentProjectId !== projectId) return;
    currentProjectPdfs = files;
    document.getElementById('project-pdfs-count').textContent = String(files.length);
    const unresolved = files.reduce((count, file) => count + file.missing_dimensions_count, 0);
    document.getElementById('project-pdfs-warning').textContent = unresolved ? `· ${unresolved} item(ns) com cota pendente` : '';
    document.getElementById('project-pdfs-panel').open = files.length > 0 && files.length <= 30;
    renderProjectPdfs();
    await refreshAiJobs(projectId);
  } catch (error) {
    if (currentProjectId === projectId) target.textContent = error.message;
  }
}

async function refreshAiJobs(projectId) {
  if (aiJobTimer) clearTimeout(aiJobTimer);
  aiJobTimer = null;
  try {
    const response = await fetch(`/api/projects/${projectId}/ai-review-jobs`);
    if (!response.ok) return;
    const data = await response.json();
    if (currentProjectId !== projectId) return;
    const previouslyDone = new Set(aiPdfJobs.filter(job => job.state === 'done')
      .map(job => `${job.path}\u0000${job.page}\u0000${job.model}`));
    aiPdfJobs = data.jobs || [];
    aiPausedUntilByModel = data.paused_until_by_model || {};
    const open = [...aiPdfExpanded];
    await Promise.all(open.map(async key => {
      const [model, path] = key.split('\u0000');
      await fetchAiPdfResult(projectId, path, model);
    }));
    renderProjectPdfs();
    if (aiPdfJobs.some(job => job.state === 'done' &&
        !previouslyDone.has(`${job.path}\u0000${job.page}\u0000${job.model}`))) {
      refreshAiPendingDimensions(projectId);
    }
    if (aiPdfJobs.some(job => ['pending', 'running', 'retry'].includes(job.state))) {
      aiJobTimer = setTimeout(() => refreshAiJobs(projectId), 3000);
    }
  } catch (error) {
    if (currentProjectId === projectId) {
      aiJobTimer = setTimeout(() => refreshAiJobs(projectId), 10000);
    }
  }
}

function setAiPendingUi(disabled, message) {
  document.querySelectorAll('.ai-import-pending-button').forEach(button => { button.disabled = disabled; });
  document.querySelectorAll('.ai-import-pending-status').forEach(status => { status.textContent = message; });
}

async function refreshAiPendingDimensions(projectId) {
  if (aiPendingBusy) return;
  setAiPendingUi(true, 'Conferindo cotas pendentes encontradas pela IA...');
  try {
    const response = await fetch(`/api/projects/${projectId}/ai-pending-dimensions`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Falha ao conferir as cotas da IA.');
    if (currentProjectId !== projectId || aiPendingBusy) return;
    let message = data.eligible_fields
      ? `${data.eligible_fields} cota(s) em ${data.eligible_items} item(ns) prontas para importar.`
      : `Nenhuma cota pendente vinculável nos resultados salvos.${data.pending_items ? ` ${data.pending_items} item(ns) ainda sem medida completa.` : ''}`;
    if (data.coded_wire_items) message += ` ${data.coded_wire_items} arame(s) identificado(s) pelo código do pai e pelo PDF filho.`;
    if (data.conflict_items) message += ` ${data.conflict_items} item(ns) com leituras conflitantes ficaram de fora.`;
    if (data.new_wire_variants) message += ` ${data.new_wire_variants} variante(s) de arame prontas para guardar, com quantidade pendente.`;
    if (data.pending_wire_quantities) message += ` ${data.pending_wire_quantities} variante(s) de arame aguardam quantidade na tabela abaixo.`;
    if (data.new_ai_items) message += ` ${data.new_ai_items} peça(s) encontradas só pela IA prontas para guardar.`;
    if (data.pending_ai_items) message += ` ${data.pending_ai_items} peça(s) da IA aguardam conferência ou quantidade total na tabela abaixo.`;
    if (data.unlinked_ai_items && !data.new_wire_variants && !data.new_ai_items && !data.pending_ai_items) message += ` ${data.unlinked_ai_items} leitura(s) dimensionais sem vínculo; confira a fonte.`;
    setAiPendingUi(false, message);
  } catch (error) {
    if (currentProjectId === projectId && !aiPendingBusy) setAiPendingUi(false, error.message);
  }
}

async function importAiPendingDimensions() {
  if (!currentProjectId || aiPendingBusy) return;
  const projectId = currentProjectId;
  aiPendingBusy = true;
  setAiPendingUi(true, 'Importando cotas pendentes já encontradas pela IA...');
  try {
    const response = await fetch(`/api/projects/${projectId}/ai-pending-dimensions`, {method: 'POST'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Falha ao importar cotas.');
    if (currentProjectId !== projectId) return;
    if (data.applied_items || data.new_wire_variants || data.new_ai_items) await loadProjectDetails(projectId);
    let message = `${data.applied_fields} cota(s) importadas em ${data.applied_items} item(ns). ${data.pending_items} item(ns) ainda sem medida completa.`;
    if (data.applied_coded_wire_items) message += ` ${data.applied_coded_wire_items} arame(s) vinculado(s) pelo código e corte do desenho filho.`;
    if (data.conflict_items) message += ` ${data.conflict_items} item(ns) com leituras conflitantes ficaram de fora.`;
    if (data.new_wire_variants) message += ` ${data.new_wire_variants} variante(s) guardadas fora do custo, com quantidade pendente.`;
    if (data.pending_wire_quantities) message += ` ${data.pending_wire_quantities} variante(s) de arame aguardam quantidade na tabela abaixo.`;
    if (data.new_ai_items) message += ` ${data.new_ai_items} peça(s) da IA guardadas para conferência de quantidade.`;
    if (data.pending_ai_items) message += ` ${data.pending_ai_items} peça(s) aguardam quantidade total ou cotejo do corte.`;
    if (data.unlinked_ai_items && !data.new_wire_variants && !data.new_ai_items && !data.pending_ai_items) message += ` ${data.unlinked_ai_items} leitura(s) dimensionais sem vínculo; confira a fonte.`;
    setAiPendingUi(true, message);
  } catch (error) {
    if (currentProjectId === projectId) setAiPendingUi(true, error.message);
  } finally {
    aiPendingBusy = false;
    if (currentProjectId === projectId) {
      document.querySelectorAll('.ai-import-pending-button').forEach(button => { button.disabled = false; });
    }
  }
}

async function fetchAiPdfResult(projectId, path, model) {
  const response = await fetch(`/api/projects/${projectId}/ai-review-pdf?${new URLSearchParams({path, model})}`);
  if (!response.ok) return;
  const result = await response.json();
  if (currentProjectId === projectId) aiPdfReviews.set(aiReviewKey(path, model), result);
}

async function toggleAiPdfResult(index) {
  const file = currentProjectPdfs[index];
  if (!file || !currentProjectId) return;
  const model = aiPdfModels.get(file.path) || aiDefaultModel;
  const key = aiReviewKey(file.path, model);
  if (aiPdfExpanded.has(key)) {
    aiPdfExpanded.delete(key);
  } else {
    aiPdfExpanded.add(key);
    await fetchAiPdfResult(currentProjectId, file.path, model);
  }
  renderProjectPdfs();
}

function renderProjectPdfs() {
  const target = document.getElementById('project-pdfs-list');
  if (!target) return;
  const query = (document.getElementById('project-pdfs-filter')?.value || '').toLocaleLowerCase();
  const files = currentProjectPdfs.filter(file => file.path.toLocaleLowerCase().includes(query));
  if (!files.length) {
    target.textContent = currentProjectPdfs.length ? 'Nenhum PDF corresponde à busca.' : 'Nenhum PDF nesta pasta.';
    return;
  }
  target.innerHTML = files.map(file => {
    const index = currentProjectPdfs.indexOf(file);
    const status = file.missing_dimensions_count
      ? `<span class="badge badge-warning">${html(file.missing_dimensions_count)} item(ns) sem cota</span>`
      : file.linked_items_count
        ? `<span class="badge badge-success">${html(file.linked_items_count)} item(ns) vinculado(s)</span>`
        : '<span class="badge badge-info">Sem item vinculado</span>';
    const model = aiPdfModels.get(file.path) || aiDefaultModel;
    const reviewKey = aiReviewKey(file.path, model);
    const stored = aiPdfReviews.get(reviewKey);
    const related = aiPdfJobs.filter(job => job.path === file.path &&
      (model === 'auto' ? aiAutoModels.includes(job.model) : job.model === model));
    const selected = new Map();
    related.forEach(job => {
      const previous = selected.get(job.page);
      if (!previous || (job.state === 'done' && previous.state !== 'done') ||
          (previous.state !== 'done' && aiAutoModels.indexOf(job.model) > aiAutoModels.indexOf(previous.model))) {
        selected.set(job.page, job);
      }
    });
    const jobs = [...selected.values()];
    const done = jobs.filter(job => job.state === 'done').length;
    const failed = jobs.filter(job => job.state === 'error').length;
    const waiting = jobs.filter(job => job.state === 'retry').length;
    const activeModel = model === 'auto' ? (jobs.find(job => ['pending', 'retry', 'running'].includes(job.state))?.model || aiAutoModels[0]) : model;
    const pausedUntil = Number(aiPausedUntilByModel[activeModel] || 0);
    const paused = pausedUntil > Date.now() / 1000 && done < jobs.length;
    const reviewStatus = jobs.length
      ? `<span class="badge ${failed ? 'badge-warning' : done === jobs.length ? 'badge-success' : 'badge-info'}">IA: ${done}/${jobs.length} página(s)${failed ? ` · ${failed} erro(s)` : ''}${waiting ? ` · ${waiting} aguardando nova tentativa` : ''}${paused ? ` · pausada até ${html(new Date(pausedUntil * 1000).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}))}` : ''}</span>`
      : '<span class="badge badge-info">IA ainda não iniciada neste modelo</span>';
    const busy = aiPdfBusy.has(`${currentProjectId}:${file.path}`);
    const details = aiPdfExpanded.has(reviewKey)
      ? `<div class="ai-review-result">${stored ? renderAiPdfPages(stored) : 'Carregando conferência...'}</div>` : '';
    const importAction = file.missing_dimensions_count && done
      ? `<button class="btn btn-sm btn-primary ai-import-pending-button" onclick="importAiPendingDimensions()" title="Importa cotas elegíveis de todas as páginas já conferidas deste projeto">Importar cotas da IA</button>`
      : '';
    return `<div class="pdf-inventory-row"><span>${sourceLink(file.source_ref)} <small>${html(file.path)}</small></span>${status}${reviewStatus}<select class="form-control ai-model-select" aria-label="Modelo de IA para este PDF" onchange="selectAiPdfModel(${index}, this.value)" ${busy ? 'disabled' : ''}><option value="auto" ${model === 'auto' ? 'selected' : ''}>Automático · 3.5 → 3.1 Lite</option><option value="gemini-3.8-flash" ${model === 'gemini-3.8-flash' ? 'selected' : ''}>Cotas complexas · 3.8 Flash</option><option value="gemini-3.5-flash-lite" ${model === 'gemini-3.5-flash-lite' ? 'selected' : ''}>3.5 Flash-Lite</option><option value="gemini-3.1-flash-lite" ${model === 'gemini-3.1-flash-lite' ? 'selected' : ''}>3.1 Flash-Lite</option></select>${importAction}<button class="btn btn-sm btn-secondary" onclick="toggleAiPdfResult(${index})">${aiPdfExpanded.has(reviewKey) ? 'Ocultar páginas' : 'Ver todas as páginas'}</button><button class="btn btn-sm btn-secondary" onclick="reviewPdf(${index})" ${busy ? 'disabled' : ''}>${busy ? 'Enfileirando...' : 'Reanalisar PDF inteiro'}</button>${details}</div>`;
  }).join('');
}

function selectAiPdfModel(index, model) {
  const file = currentProjectPdfs[index];
  if (!file || !['auto', 'gemini-3.8-flash', ...aiAutoModels].includes(model)) return;
  aiPdfModels.set(file.path, model);
  renderProjectPdfs();
}

const aiFieldNames = {length:'Comprimento', width:'Largura', depth:'Profundidade/altura', thickness:'Espessura', radius_diam:'Diâmetro', quantity:'Quantidade', unit_weight_g:'Peso unitário (g)'};
const aiStateNames = {agree:'Confere', different:'Diverge', ai_only:'Só IA', script_only:'Só script', unverified:'Escopo distinto'};

function renderAiReview(data) {
  if (data.error) return `<span class="badge badge-warning">${html(data.error)}</span>`;
  if (!data.available) return 'Ainda não conferido.';
  const review = data.review;
  const rows = data.comparisons.map(entry => {
    const item = entry.ai_item;
    const fields = entry.fields.map(field => `<div class="ai-review-field ai-review-${field.state}"><b>${html(aiFieldNames[field.field] || field.field)}:</b> script ${html(field.script ?? '—')} · IA ${html(field.ai ?? '—')} <span class="badge ${field.state === 'agree' ? 'badge-success' : field.state === 'different' ? 'badge-warning' : 'badge-info'}">${html(aiStateNames[field.state])}</span></div>`).join('');
    return `<div class="ai-review-item"><b>${html(item.item_number ? item.item_number + ' · ' : '')}${html(item.description)}</b> <small>${html(item.material)} · ${html(item.dimension_basis)}</small>${entry.script_item_id ? `<small> ↔ item do script #${html(entry.script_item_id)} (${html(entry.script_description)})</small>` : '<span class="badge badge-warning">Sem item correspondente no script</span>'}${fields || '<small>Sem cota numérica segura</small>'}<small>Fonte visual: ${html(item.evidence || 'não indicada')}</small>${item.warnings.map(w => `<small>⚠ ${html(w)}</small>`).join('')}${entry.script_item_id ? `<button class="btn btn-sm btn-secondary" onclick="openEditMaterialModal(${Number(entry.script_item_id)})">Conferir e editar item</button>` : ''}</div>`;
  }).join('');
  const scriptOnly = data.script_only.map(item => `<small>Sem correspondência da IA: #${html(item.id)} ${html(item.description)}</small>`).join('');
  return `<div><b>Conferência visual · página ${html(review.page)} · ${html(review.model)}</b><small>${html(review.result.drawing_title || '')}</small>${rows || '<small>Nenhum item identificado pela IA.</small>'}${scriptOnly}${review.result.notes.map(note => `<small>⚠ ${html(note)}</small>`).join('')}</div>`;
}

function renderAiPdfPages(data) {
  if (!data.pages.length) return 'Nenhuma página enfileirada neste modelo.';
  return data.pages.map(page => {
    const retryTime = Number(page.next_attempt_at) > Date.now() / 1000
      ? ` às ${new Date(Number(page.next_attempt_at) * 1000).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'})}` : '';
    const retryText = page.error?.includes('HTTP 503')
      ? `Serviço Google temporariamente indisponível; nova tentativa automática${retryTime}.`
      : `Aguardando nova tentativa automática${retryTime}${page.error ? ` · ${page.error}` : ''}`;
    const message = page.state === 'retry' ? retryText
      : page.error || (page.state === 'running' ? 'Analisando...' : page.state === 'error' ? 'Falha na leitura' : 'Na fila...');
    return `<div class="ai-review-page"><b>Página ${html(page.page)} · ${html(page.model)}:</b> ${page.result ? renderAiReview(page.result) : html(message)}</div>`;
  }).join('');
}

async function reviewPdf(index) {
  const file = currentProjectPdfs[index];
  if (!file || !currentProjectId) return;
  const model = aiPdfModels.get(file.path) || aiDefaultModel;
  const reviewKey = aiReviewKey(file.path, model);
  const busyKey = `${currentProjectId}:${file.path}`;
  if (aiPdfBusy.has(busyKey)) return;
  const projectId = currentProjectId;
  aiPdfBusy.add(busyKey);
  aiPdfExpanded.add(reviewKey);
  renderProjectPdfs();
  try {
    const response = await fetch(`/api/projects/${projectId}/ai-review-pdf`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path:file.path, model, force:true})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Falha na consulta.');
    if (currentProjectId === projectId) await refreshAiJobs(projectId);
  } catch (error) {
    if (currentProjectId === projectId) alert(error.message);
  } finally {
    aiPdfBusy.delete(busyKey);
  }
  if (currentProjectId === projectId) renderProjectPdfs();
}

function renderAssemblyTree() {
  const target = document.getElementById('assembly-tree');
  if (!target || !currentProjectData) return;
  const root = {name: currentProjectData.project.name, children: new Map(), items: [], references: [], assembly: null};
  const mainName=(currentProjectData.materials.find(m => m.parent_assembly)?.parent_assembly || '')
    .split(' / ')[0].trim() || currentProjectData.project.name;
  for (const m of currentProjectData.materials) {
    const parts = (m.parent_assembly || '').split(' / ').map(x => x.trim()).filter(Boolean);
    if (!parts.length) parts.push(mainName);
    let node = root;
    for (const part of parts) {
      if (!node.children.has(part)) node.children.set(part, {name: part, children: new Map(), items: [], references: [], assembly: null});
      node = node.children.get(part);
    }
    if (m.item_type === 'subconjunto') {
      if (!node.children.has(m.description)) node.children.set(m.description, {name: m.description, children: new Map(), items: [], references: [], assembly: null});
      node.children.get(m.description).assembly = m;
      continue;
    }
    node.items.push(m);
    if (m.mirrored_assembly) {
      let mirrorNode = root;
      for (const part of m.mirrored_assembly.split(' / ').map(x => x.trim()).filter(Boolean)) {
        if (!mirrorNode.children.has(part)) mirrorNode.children.set(part, {name: part, children: new Map(), items: [], references: [], assembly: null});
        mirrorNode = mirrorNode.children.get(part);
      }
      mirrorNode.references.push(m);
    }
  }
  function count(node) {
    return node.items.length + [...node.children.values()].reduce((sum, child) => sum + count(child), 0);
  }
  function markup(node, level=0, parentQuantity=1) {
    const assembly=node.assembly;
    const effectiveQuantity=assembly ? Number(assembly.quantity) : parentQuantity;
    const children=[...node.children.values()].map(child => markup(child,level+1,effectiveQuantity)).join('');
    const labels={materia_prima:'Matéria-prima',comprado:'Item comprado'};
    const items=node.items.map(m => `<div class="assembly-piece"><span class="badge badge-info">${labels[m.item_type] || 'Item'}</span> ${html(m.quantity)} ${html(m.unit)} · ${html(m.description)} ${m.mirrored_assembly ? '<small>(quantidade D/E)</small>' : m.sides_total_quantity ? `<small>(total D/E: ${html(m.sides_total_quantity)} ${html(m.unit)})</small>` : ''} ${m.is_inferred ? '<span class="badge badge-info">↔ Espelhado</span>' : ''} <small>(${sourceLink(m.source_page)})</small></div>`).join('');
    const references=node.references.map(m => `<div class="assembly-piece"><small>${html(m.description)} · incluído nas ${html(m.quantity)} ${html(m.unit)} dos dois lados</small></div>`).join('');
    const role=level===1 ? 'Corpo principal' : level>1 ? 'Subconjunto' : 'Projeto';
    const ownCount=count(node);
    const itemLabel=ownCount ? `${ownCount} peças` : `${node.references.length} vinculadas`;
    const localQuantity=assembly ? effectiveQuantity / parentQuantity : 0;
    const amount=assembly ? `<span class="badge badge-info">${html(localQuantity)} por pai · ${html(effectiveQuantity)} no produto</span>` : '';
    const edit=assembly ? `<div class="assembly-piece"><button class="btn btn-sm btn-secondary" onclick="openEditMaterialModal(${assembly.id})">Editar quantidade do conjunto</button>${!ownCount && !node.references.length ? ' ⚠️ Composição ainda não detalhada' : ''}</div>` : '';
    return `<details ${level <= 1 ? 'open' : ''}><summary>${role}: ${html(node.name)} ${amount} <span class="badge badge-info">${itemLabel}</span></summary>${edit}${children}${items}${references}</details>`;
  }
  target.innerHTML = currentProjectData.materials.length ? markup(root) : 'Nenhum item importado.';
}

// 2. IMPORTAÇÃO
async function importFromFolder() {
  if (!currentProjectId) {
    return alert("Por favor selecione ou crie um projeto antes de importar.");
  }
  const folder = document.getElementById("import-folder-input").value.trim();
  if (!folder) return alert("Por favor informe o caminho da pasta.");

  const logBox = document.getElementById("import-log-box");
  const logText = document.getElementById("import-log-text");
  logBox.style.display = "block";
  logText.innerText = "Escanenado PDFs, cotas, tabelas BOM e carimbos técnicos...";

  try {
    const res = await fetch(`/api/projects/${currentProjectId}/import-folder`, {
      method: "POST",
      body: new URLSearchParams({folder_path: folder})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha na leitura da pasta.');
    logText.innerText = data.message;
    await loadProjectDetails(currentProjectId);
    setTimeout(() => { switchView("view-bom"); }, 1000);
  } catch (e) {
    logText.innerText = "Erro na importação: " + e.message;
  }
}

async function uploadSelectedPdfs(inputId, folderMode) {
  if (!currentProjectId) {
    return alert("Por favor selecione ou crie um projeto primeiro.");
  }
  const input=document.getElementById(inputId);
  const files=[...input.files].filter(file => file.name.toLowerCase().endsWith('.pdf'));
  if (!files.length) return alert(folderMode ? 'A pasta não contém PDFs.' : 'Selecione um arquivo PDF.');
  if (files.length>1000) return alert('Selecione uma pasta com até 1000 PDFs.');
  if (folderMode && files.some(file => !file.webkitRelativePath)) {
    return alert('O navegador não informou as subpastas. Use o caminho da pasta ou ZIP/RAR.');
  }
  const formData=new FormData();
  files.forEach(file => {
    formData.append('files',file,file.name);
    formData.append('paths',folderMode ? file.webkitRelativePath : file.name);
  });
  const logBox=document.getElementById('import-log-box');
  const logText=document.getElementById('import-log-text');
  logBox.style.display='block';
  logText.innerText=`Enviando ${files.length} PDF(s) e lendo o projeto...`;
  try {
    const res=await fetch(`/api/projects/${currentProjectId}/upload-files`,{method:'POST',body:formData});
    const data=await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha no envio dos PDFs.');
    logText.innerText=data.message;
    await loadProjectDetails(currentProjectId);
    setTimeout(() => switchView('view-bom'),1000);
  } catch (error) {
    logText.innerText='Erro na importação: '+error.message;
  }
}

async function uploadArchive() {
  if (!currentProjectId) return alert('Selecione ou crie um projeto primeiro.');
  const fileInput = document.getElementById("import-archive-input");
  if (!fileInput.files.length) return alert("Selecione um arquivo ZIP ou RAR.");
  if (!/\.(zip|rar)$/i.test(fileInput.files[0].name)) return alert('Envie ZIP ou RAR.');

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  const logBox = document.getElementById("import-log-box");
  const logText = document.getElementById("import-log-text");
  logBox.style.display = "block";
  logText.innerText = "Enviando arquivo compactado e extraindo os PDFs...";

  try {
    const res = await fetch(`/api/projects/${currentProjectId}/upload-archive`, {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha no envio do ZIP.');
    logText.innerText = data.message;
    await loadProjectDetails(currentProjectId);
    setTimeout(() => { switchView("view-bom"); }, 1000);
  } catch (e) {
    logText.innerText = "Erro no envio: " + e.message;
  }
}

// 3. BOM (LISTA DE MATERIAIS)
function renderMaterialsTable() {
  if (!currentProjectData) return;
  const materials = currentProjectData.materials;
  const filterGroup = document.getElementById("bom-filter-group").value;
  const filterType = document.getElementById("bom-filter-type").value;
  const search = (document.getElementById("bom-filter-search")?.value || '').trim().toLocaleLowerCase();
  const tbody = document.getElementById("bom-tbody");
  tbody.innerHTML = "";

  const filtered = materials.filter(m => m.item_type !== 'subconjunto' && (filterGroup === 'ALL' || m.group_name === filterGroup) &&
    (filterType === 'ALL' || m.item_type === filterType) &&
    (!search || [m.description, m.drawing_id, m.raw_code, m.material].some(value => String(value || '').toLocaleLowerCase().includes(search))));
  const ordered = ['materia_prima','comprado'].flatMap(type => filtered.filter(m => m.item_type === type));

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="17" style="text-align: center; padding: 25px;">Nenhum item encontrado no filtro selecionado.</td></tr>`;
    return;
  }

  let sumQty = 0;
  let sumWeight = 0;
  let sumArea = 0;
  let sumCost = 0;

  const typeLabels={materia_prima:'Matéria-prima',comprado:'Itens comprados'};
  let section='';
  ordered.forEach(m => {
    if (section !== m.item_type) {
      section=m.item_type;
      const heading=document.createElement('tr');
      heading.innerHTML=`<td colspan="17" style="background:#eef2f7;font-weight:700;">${typeLabels[section] || 'Itens'}</td>`;
      tbody.appendChild(heading);
    }
    sumQty += m.quantity;
    if (m.item_type !== 'subconjunto') {
      sumWeight += m.total_weight;
      sumArea += m.total_area;
      sumCost += m.total_price || 0;
    }

    // Confiança Badge
    let confBadge = `<span class="badge badge-success">100%</span>`;
    if (m.confidence < 0.85 && m.confidence >= 0.70) {
      confBadge = `<span class="badge badge-warning">${Math.round(m.confidence * 100)}%</span>`;
    } else if (m.confidence < 0.70) {
      confBadge = `<span class="badge badge-danger">${Math.round(m.confidence * 100)}%</span>`;
    }

    // Dimensões Formatadas
    let dimStr = "-";
    if (m.group_name === 'Tubo Redondo' && m.radius_diam > 0 && m.length > 0) {
      dimStr = `Ø${m.radius_diam}x${m.thickness} mm · ${m.length} mm`;
    } else if (m.group_name === 'Tubo Quadrado/Retangular' && m.length > 0 && m.width > 0 && m.depth > 0) {
      dimStr = `${m.width}x${m.depth}x${m.thickness} mm · ${m.length} mm`;
    } else if (m.radius_diam > 0 && m.length > 0) {
      dimStr = `Ø${m.radius_diam} x ${m.length}`;
    } else if (m.length > 0 && m.width > 0) {
      dimStr = `${m.length}x${m.width}`;
      if (m.thickness > 0) dimStr += `x${m.thickness}`;
    } else if (m.length > 0) {
      dimStr = `${m.length}`;
    } else if (m.width > 0) {
      dimStr = `${m.width}`;
    }
    const outline = /Cotas gerais do desenho:\s*([\d.,×xX]+)\s*mm/i.exec(m.observation || "");
    if (outline) {
      dimStr = `Cotas externas: ${html(outline[1])} mm`;
      if (m.group_name === 'Tubo Quadrado/Retangular' && m.width > 0 && m.depth > 0) {
        dimStr += `<br/><small>Perfil: ${html(`${m.width}×${m.depth}×${m.thickness} mm`)}</small>`;
      }
    }
    // The size after the hyphen in a sheet material is the raw commercial
    // sheet. Show it separately from the cut piece used for mass and price.
    const sheetMaterial = /\b(?:CHAPA|PSAI|PVC|PETG|ACR[IÍ]LICO)\b/i.test(m.material || "");
    const stock = sheetMaterial && /(?:-|–)\s*(\d{3,4}(?:[,.]\d+)?)\s*[xX×]\s*(\d{3,4}(?:[,.]\d+)?)/i.exec(m.material || "");
    if (stock) {
      const gauge = m.thickness || Number((/(\d+(?:[,.]\d+)?)\s*(?:-|–)\s*\d{3,4}/.exec(m.material || "") || [])[1]?.replace(',', '.')) || 0;
      const rawSize = `${stock[1]}×${stock[2]}${gauge ? `×${gauge}` : ''} mm`;
      if (dimStr === "-") dimStr = "Peça: cota pendente";
      dimStr += `<br/><small>Chapa de origem: ${html(rawSize)}</small>`;
    }
    if (m.wire_allowance_mm) {
      dimStr += `<br/><small>Corte: ${html(m.drawing_length)} + ${html(m.wire_allowance_mm)} mm</small>`;
    }

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${m.item_num}</td>
      <td><b>${m.quantity}</b> ${m.unit}${m.mirrored_assembly ? '<br/><small>Inclui os dois lados</small>' : m.sides_total_quantity ? `<br/><small>Total D/E: ${html(m.sides_total_quantity)} ${html(m.unit)}</small>` : ''}</td>
      <td>
        <b>${html(m.description)}</b>
        ${m.drawing_id || m.raw_code ? `<br/><small>Desenho: ${html(m.drawing_id || '—')} · Código MP: ${html(m.raw_code || '—')}</small>` : ''}
        ${m.mirrored_assembly ? '<span class="badge badge-info" style="margin-left:4px;">D/E na quantidade</span>' : m.is_consolidated ? '<span class="badge badge-info" style="margin-left:4px;">Consolidado</span>' : ''}
        ${m.is_inferred ? '<span class="badge badge-info" style="margin-left:4px;">↔ Espelhado</span>' : ''}
        ${m.observation ? `<details><summary style="cursor:pointer;color:var(--text-muted);">Verificação / observações</summary><small>${html(m.observation)}</small></details>` : ''}
        ${m.pending_issue ? `<br/><small style="color:var(--danger);">⚠️ ${html(m.pending_issue)}</small>` : ''}
      </td>
      <td><span class="badge badge-info">${m.item_type === 'materia_prima' ? 'Matéria-prima' : m.item_type === 'comprado' ? 'Comprado' : 'Subconjunto'}</span></td>
      <td><span class="badge" style="background:#f1f5f9; color:#475569;">${html(m.group_name)}</span></td>
      <td><small>${html(m.material || "-")}</small></td>
      <td><small>${dimStr}</small></td>
      <td>${m.item_type === 'subconjunto' ? '—' : m.unit_weight === 0 && /peso/i.test(m.pending_issue || '') ? 'Pendente' : m.unit_weight.toFixed(3)}</td>
      <td><b>${m.item_type === 'subconjunto' ? '—' : m.unit_weight === 0 && /peso/i.test(m.pending_issue || '') ? 'Pendente' : m.total_weight.toFixed(3)}</b></td>
      <td>${m.total_area.toFixed(3)}</td>
      <td><span class="badge" style="background:#e0f2fe; color:#0369a1;">${m.printing || "0x0"}</span></td>
      <td>${m.item_type === 'subconjunto' ? '—' : m.unit_price == null ? '<span class="badge badge-danger">Pendente</span>' : 'R$ ' + m.unit_price.toFixed(2)}</td>
      <td><b>${m.item_type === 'subconjunto' ? '—' : m.total_price == null ? 'Pendente' : 'R$ ' + m.total_price.toFixed(2)}</b></td>
      <td><small style="color:var(--text-muted);">${html(m.price_source || "-")}</small></td>
      <td><small>${sourceLink(m.source_page)}</small></td>
      <td>${confBadge}</td>
      <td>
        <button class="btn btn-sm btn-secondary" onclick="openEditMaterialModal(${m.id})">✏️</button>
        <button class="btn btn-sm btn-danger" onclick="deleteMaterialItem(${m.id})">🗑️</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  const tfoot = document.getElementById("bom-tfoot");
  tfoot.innerHTML = `
    <tr>
      <td colspan="8"><b>TOTAL FILTRADO (${filtered.length} itens)</b></td>
      <td><b>${sumWeight.toFixed(3)} kg</b></td>
      <td><b>${sumArea.toFixed(3)} m²</b></td>
      <td colspan="2"></td>
      <td><b>R$ ${sumCost.toLocaleString("pt-BR", {minimumFractionDigits: 2})}</b></td>
      <td colspan="4"></td>
    </tr>
  `;
}

function renderWireVariants() {
  const variants = currentProjectData?.wire_variants || [];
  const panel = document.getElementById('wire-variants-panel');
  const tbody = document.getElementById('wire-variants-tbody');
  if (!panel || !tbody) return;
  panel.style.display = variants.length ? 'block' : 'none';
  tbody.innerHTML = variants.map(v => `<tr>
    <td><b>${html(v.code)}</b></td>
    <td>${html(v.nominal)}</td>
    <td>${html(v.measure_a)} mm</td>
    <td><b>${html(v.cut_length)} mm</b><br/><small>Consumo após seleção: +20 mm para solda</small></td>
    <td>${html(v.material)}</td>
    <td>${v.ai_agreement_count ? `${v.ai_agreement_count} modelo(s) concordam com o PDF` : 'Tabela do PDF'}</td>
    <td>${v.material_id ? `<b>${html(v.current_quantity)} un no orçamento</b>` :
      `<input id="wire-variant-qty-${v.id}" class="form-control" type="number" min="0.001" step="any" placeholder="Qtd" style="max-width:90px;display:inline-block;" aria-label="Quantidade do código ${html(v.code)}"> <button class="btn btn-sm btn-primary" onclick="selectWireVariant(${v.id})">Adicionar</button>`}</td>
    <td><small>${sourceLink(v.source_page)}</small></td>
  </tr>`).join('');
}

async function selectWireVariant(id) {
  if (!currentProjectId) return;
  const value = Number(document.getElementById(`wire-variant-qty-${id}`)?.value);
  if (!Number.isFinite(value) || value <= 0) return alert('Informe a quantidade dessa variante.');
  const response = await fetch(`/api/projects/${currentProjectId}/wire-variants/${id}/material`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({quantity: value})
  });
  if (!response.ok) return alert((await response.json()).detail || 'Erro ao adicionar variante.');
  await loadProjectDetails(currentProjectId);
}

function renderAiDiscoveredItems() {
  const rows = currentProjectData?.ai_discovered_items || [];
  const panel = document.getElementById('ai-discovered-panel');
  const tbody = document.getElementById('ai-discovered-tbody');
  if (!panel || !tbody) return;
  panel.style.display = rows.length ? 'block' : 'none';
  tbody.innerHTML = rows.map(item => {
    const dimensions = JSON.parse(item.dimensions_json || '{}');
    const labels = {length: 'C', width: 'L', depth: 'P', thickness: 'Esp.', radius_diam: 'Ø'};
    const size = Object.entries(dimensions).map(([key, value]) => `${labels[key] || key}: ${value}`).join(' · ');
    const action = item.material_id
      ? `<b>${html(item.current_quantity)} un no orçamento</b>`
      : item.ready
        ? `<input id="ai-item-qty-${item.id}" class="form-control" type="number" min="0.001" step="any" placeholder="Qtd total" style="max-width:100px;display:inline-block;" aria-label="Quantidade total de ${html(item.description)}"> <button class="btn btn-sm btn-primary" onclick="selectAiDiscoveredItem(${item.id})">Adicionar</button>`
        : '<span class="text-warning">Corte ou cotas incompletos; conferir</span>';
    return `<tr><td><b>${html(item.description)}</b></td><td>${html(item.material)}</td>
      <td>${html(size)}</td><td><small>${html(item.evidence)}</small></td>
      <td>${action}</td><td><small>${sourceLink(item.source_page)}</small></td></tr>`;
  }).join('');
}

async function selectAiDiscoveredItem(id) {
  if (!currentProjectId) return;
  const quantity = Number(document.getElementById(`ai-item-qty-${id}`)?.value);
  if (!Number.isFinite(quantity) || quantity <= 0) return alert('Informe a quantidade total dessa peça no projeto.');
  const response = await fetch(`/api/projects/${currentProjectId}/ai-discovered-items/${id}/material`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({quantity})
  });
  if (!response.ok) return alert((await response.json()).detail || 'Erro ao adicionar peça.');
  await loadProjectDetails(currentProjectId);
}

function openEditMaterialModal(id) {
  const m = currentProjectData.materials.find(x => x.id === id);
  if (!m) return;

  document.getElementById("em-id").value = m.id;
  document.getElementById("em-title").innerText = `Editar: ${m.description}`;
  document.getElementById("em-desc").value = m.description;
  document.getElementById("em-group").value = m.group_name;
  document.getElementById("em-type").value = m.item_type || 'comprado';
  document.getElementById("em-parent").value = m.parent_assembly || '';
  document.getElementById("em-material").value = m.material || "";
  document.getElementById("em-qty").value = m.quantity;
  document.getElementById("em-len").value = m.length;
  document.getElementById("em-len-label").innerText = m.group_name === 'Arame'
    ? 'Comprimento de corte (mm, inclui 20 mm para solda):' : 'Comprimento (mm):';
  document.getElementById("em-width").value = m.width;
  document.getElementById("em-depth").value = m.depth;
  document.getElementById("em-unit").value = m.unit || 'un';
  document.getElementById("em-thk").value = m.thickness;
  document.getElementById("em-diam").value = m.radius_diam;
  document.getElementById("em-print").value = m.printing || "0x0";
  document.getElementById("em-weight").value = m.unit_weight;
  document.getElementById("em-price").value = m.unit_price ?? "";
  document.getElementById("em-obs").value = m.observation || "";
  document.getElementById("em-pending").value = m.pending_issue || "";

  openModal("modal-edit-material");
}

function openNewMaterialModal() {
  document.getElementById("em-id").value = "";
  document.getElementById("em-title").innerText = "Adicionar componente / material";
  for (const id of ["em-desc","em-material","em-parent","em-qty","em-len","em-width","em-depth","em-thk","em-diam","em-weight","em-price","em-obs","em-pending"]) {
    document.getElementById(id).value = "";
  }
  document.getElementById("em-qty").value = "1";
  document.getElementById("em-group").value = "Chapa";
  document.getElementById("em-type").value = "materia_prima";
  document.getElementById("em-unit").value = "un";
  document.getElementById("em-print").value = "0x0";
  openModal("modal-edit-material");
}

async function submitEditMaterial() {
  if (materialSaveInFlight) return;
  materialSaveInFlight = true;
  const projectId = currentProjectId;
  const saveButton = document.getElementById('save-material-button');
  if (saveButton) saveButton.disabled = true;
  try {
  const id = document.getElementById("em-id").value;
  const payload = {
    description: document.getElementById("em-desc").value,
    group_name: document.getElementById("em-group").value,
    item_type: document.getElementById("em-type").value,
    parent_assembly: document.getElementById("em-parent").value,
    material: document.getElementById("em-material").value,
    quantity: parseFloat(document.getElementById("em-qty").value),
    unit: document.getElementById("em-unit").value,
    length: parseFloat(document.getElementById("em-len").value) || 0.0,
    width: parseFloat(document.getElementById("em-width").value) || 0.0,
    depth: parseFloat(document.getElementById("em-depth").value) || 0.0,
    thickness: parseFloat(document.getElementById("em-thk").value) || 0.0,
    radius_diam: parseFloat(document.getElementById("em-diam").value) || 0.0,
    printing: document.getElementById("em-print").value,
    unit_weight: parseFloat(document.getElementById("em-weight").value) || 0.0,
    observation: document.getElementById("em-obs").value,
    pending_issue: document.getElementById("em-pending").value
  };
  const priceText = document.getElementById("em-price").value.trim();
  const oldItem = id ? currentProjectData.materials.find(x => String(x.id) === String(id)) : null;
  const enteredPrice = priceText ? parseFloat(priceText.replace(',', '.')) : null;
  if (!oldItem || enteredPrice !== oldItem.unit_price) payload.unit_price = enteredPrice;

  const res = await fetch(id ? `/api/projects/${projectId}/materials/${id}` : `/api/projects/${projectId}/materials`, {
    method: id ? "PUT" : "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  const responseText = await res.text();
  let responseData;
  try {
    responseData = responseText ? JSON.parse(responseText) : {};
  } catch {
    if (!res.ok) responseData = {detail: responseText};
    else throw new Error(`Resposta inválida do servidor (HTTP ${res.status}).`);
  }
  if (!res.ok) {
    const message = responseData?.detail || responseData?.message || `Erro HTTP ${res.status} ao salvar item.`;
    return alert(message);
  }
  const saved = responseData;
  closeModal("modal-edit-material");
  await loadProjectDetails(projectId);
  if (saved.descendants_updated) {
    alert(`Quantidade do conjunto atualizada em ${saved.descendants_updated} peça(s) e subconjunto(s) internos.`);
  }
  if (saved.validation?.show) {
    const v=saved.validation;
    const grams=kg => (kg*1000).toLocaleString('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:3});
    const lines=[`Peso calculado: ${grams(v.calculated_weight)} g`,
      v.source_linked ? `Peso do PDF: ${grams(v.pdf_weight)} g` : 'Peso do PDF: não vinculado',
      `Peso adotado: ${grams(v.adopted_weight)} g`];
    if (v.adjusted) lines.push('O peso informado ficou abaixo do mínimo e foi ajustado.');
    if (v.drawing_difference) lines.push(`Medidas diferentes do PDF: ${v.drawing_difference}`);
    if (!v.calculated_weight) lines.push('Não foi possível validar pela geometria; confira as medidas.');
    alert(lines.join('\n'));
  }
  } catch (error) {
    alert(error?.message || 'Não foi possível salvar a edição. Tente novamente.');
  } finally {
    materialSaveInFlight = false;
    if (saveButton) saveButton.disabled = false;
  }
}

async function deleteMaterialItem(id) {
  if (!confirm("Tem certeza que deseja remover este item da BOM?")) return;
  await fetch(`/api/projects/${currentProjectId}/materials/${id}`, {method: "DELETE"});
  await loadProjectDetails(currentProjectId);
}

// 4. CONFERÊNCIA DE PESO
function renderWeightView() {
  if (!currentProjectData) return;
  const w = currentProjectData.weight_result;
  const mk = currentProjectData.markup_result;

  document.getElementById("weight-steel-val").innerText = `${w.total_steel_weight.toFixed(3)} kg`;
  document.getElementById("weight-steel-hist").innerText = `Histórico: ${w.historical_steel_weight > 0 ? w.historical_steel_weight.toFixed(3) + ' kg' : 'N/A'}`;

  document.getElementById("weight-total-val").innerText = `${w.total_product_weight.toFixed(3)} kg`;
  document.getElementById("weight-pdf-ref").innerText = `Carimbo PDF: ${w.nominal_pdf_weight > 0 ? w.nominal_pdf_weight.toFixed(3) + ' kg' : 'N/A'}`;

  const deltaElem = document.getElementById("weight-delta-val");
  const deltaStatusElem = document.getElementById("weight-delta-status");
  deltaElem.innerText = `${w.delta_pdf_pct.toFixed(1)}%`;
  
  if (w.status_pdf_compare === "OK") {
    deltaElem.style.color = "var(--success)";
    deltaStatusElem.innerText = "Status: Consistente (dentro da tolerância)";
  } else if (w.status_pdf_compare === "DIVERGENCIA") {
    deltaElem.style.color = "var(--danger)";
    deltaStatusElem.innerText = `⚠️ Divergente (${w.delta_pdf_val > 0 ? '+' : ''}${w.delta_pdf_val.toFixed(3)} kg)`;
  } else if (w.status_pdf_compare === "INCOMPLETO") {
    deltaElem.style.color = "var(--warning)";
    deltaStatusElem.innerText = `Conferência incompleta: ${w.missing_weight_count} itens sem peso`;
  } else {
    deltaElem.style.color = "var(--text-muted)";
    deltaStatusElem.innerText = "Sem referência nominal";
  }
  const missingPreview=(w.missing_weight_items || []).slice(0,8)
    .map(x => `${html(x.description)} (${html(x.quantity)} un)`).join(', ');
  document.getElementById('weight-audit-note').innerHTML =
    `${html(w.pdf_alert_message)}<br/>Arame para corte/solda: +20 mm por peça com medida disponível; `+
    `extra de material: ${w.wire_extra_weight.toFixed(3)} kg. `+
    `Peso de corte total: ${w.total_cut_weight.toFixed(3)} kg.`+
    (missingPreview ? `<br/><b>Sem peso:</b> ${missingPreview}${w.missing_weight_count>8 ? '…' : ''}` : '');

  document.getElementById("weight-price-kg").innerText = `R$ ${mk.preco_kg_aco.toFixed(2)} / kg`;

  // Tabela por Grupo
  const groupsTbody = document.getElementById("weight-groups-tbody");
  groupsTbody.innerHTML = "";
  for (const [grp, weight] of Object.entries(w.group_weights)) {
    const pct = w.total_product_weight > 0 ? (weight / w.total_product_weight * 100) : 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><b>${grp}</b></td>
      <td>${weight.toFixed(3)} kg</td>
      <td>${pct.toFixed(1)}%</td>
    `;
    groupsTbody.appendChild(tr);
  }

  // Top Peças
  const topTbody = document.getElementById("weight-top-tbody");
  topTbody.innerHTML = "";
  (w.top_heavy_parts || []).forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><b>${p.description}</b><br/><small style="color:var(--text-muted);">${p.group}</small></td>
      <td>${p.quantity} un</td>
      <td><b>${p.total_weight.toFixed(3)} kg</b></td>
      <td><small>${p.drawing_id || "-"}</small></td>
    `;
    topTbody.appendChild(tr);
  });
}

// 5. CUSTOS E MARKUP
function renderMarkupView() {
  if (!currentProjectData) return;
  const mk = currentProjectData.markup_result;
  const cfg = currentProjectData.markup_config;

  document.getElementById("mk-preco-sugerido").innerText = `R$ ${mk.preco_sugerido_total.toLocaleString("pt-BR", {minimumFractionDigits: 2})}`;
  document.getElementById("mk-custo-total").innerText = `R$ ${mk.cost_total.toLocaleString("pt-BR", {minimumFractionDigits: 2})}`;
  document.getElementById("mk-custo-split").innerText = `MP: R$ ${mk.cost_mp.toFixed(2)} | Comprado: R$ ${mk.cost_mc.toFixed(2)}`;
  document.getElementById("mk-margem-pond").innerText = `${mk.margem_ponderada_pct.toFixed(2)}%`;

  // Matéria-Prima
  document.getElementById("badge-fator-mp").innerText = `Fator MK: ${mk.fator_mp.toFixed(4)}x`;
  document.getElementById("lbl-custo-mp").innerText = `R$ ${mk.cost_mp.toFixed(2)}`;
  document.getElementById("lbl-preco-mp").innerText = `R$ ${mk.preco_sugerido_mp.toFixed(2)}`;
  document.getElementById("mk-margin-mp-input").value = cfg.margin_mp;

  const moTbody = document.getElementById("mk-mo-tbody");
  moTbody.innerHTML = "";
  (mk.mo_breakdown_mp || []).forEach((item, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" id="mo-active-${idx}" ${item.active ? 'checked' : ''} onchange="updateMoRow(${idx})"></td>
      <td>${item.name}</td>
      <td><input type="number" id="mo-pct-${idx}" value="${item.pct}" step="0.1" style="width: 60px; padding: 2px 4px;" onchange="updateMoRow(${idx})">%</td>
      <td>R$ ${item.val.toFixed(2)}</td>
    `;
    moTbody.appendChild(tr);
  });

  // Material Comprado
  document.getElementById("badge-fator-mc").innerText = `Fator MK: ${mk.fator_mc.toFixed(4)}x`;
  document.getElementById("lbl-custo-mc").innerText = `R$ ${mk.cost_mc.toFixed(2)}`;
  document.getElementById("lbl-preco-mc").innerText = `R$ ${mk.preco_sugerido_mc.toFixed(2)}`;
  document.getElementById("mk-margin-mc-input").value = cfg.margin_mc;

  const opTbody = document.getElementById("mk-op-tax-tbody");
  opTbody.innerHTML = "";
  [...(mk.op_breakdown_mc || []), ...(mk.tax_breakdown_mc || [])].forEach((item, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="badge badge-success">Ativo</span></td>
      <td>${item.name}</td>
      <td>${item.pct.toFixed(2)}%</td>
      <td>R$ ${item.val.toFixed(2)}</td>
    `;
    opTbody.appendChild(tr);
  });
}

function updateMoRow(idx) {
  if (!currentProjectData) return;
  const active = document.getElementById(`mo-active-${idx}`).checked;
  const pct = parseFloat(document.getElementById(`mo-pct-${idx}`).value) || 0.0;
  currentProjectData.markup_config.mo_items[idx].active = active;
  currentProjectData.markup_config.mo_items[idx].effective_pct = pct;
}

async function saveMarkupConfig() {
  if (!currentProjectId) return;
  const cfg = currentProjectData.markup_config;
  cfg.margin_mp = parseFloat(document.getElementById("mk-margin-mp-input").value) || 18.0;
  cfg.margin_mc = parseFloat(document.getElementById("mk-margin-mc-input").value) || 18.0;

  await fetch(`/api/projects/${currentProjectId}/markup`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(cfg)
  });
  alert("Parâmetros de markup salvos com sucesso!");
  await loadProjectDetails(currentProjectId);
}

// 6. PENDÊNCIAS
function renderPendingView() {
  if (!currentProjectData) return;
  const pendings = currentProjectData.pending_decisions;
  const tbody = document.getElementById("pendencias-tbody");
  tbody.innerHTML = "";

  if (pendings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 25px;"><b>Nenhuma decisão de extração aberta.</b> Verifique também os preços, o peso e o markup antes da emissão final.</td></tr>`;
    return;
  }

  pendings.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><b>${p.title}</b></td>
      <td>${p.description}</td>
      <td><span class="badge badge-warning">${p.impact_level}</span></td>
      <td><small>${p.proposed_action}</small></td>
      <td><span class="badge ${p.status === 'APROVADO' ? 'badge-success' : 'badge-warning'}">${p.status}</span></td>
      <td>
        ${p.status === 'PENDENTE' ? `
          <button class="btn btn-sm btn-success" onclick="resolvePendingItem(${p.id}, 'APROVADO')">✓ Aprovar</button>
          <button class="btn btn-sm btn-danger" onclick="resolvePendingItem(${p.id}, 'REJEITADO')">✕ Rejeitar</button>
        ` : `<span>Resolvido</span>`}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function resolvePendingItem(id, status) {
  await fetch(`/api/projects/${currentProjectId}/pending/${id}/resolve`, {
    method: "POST",
    body: new URLSearchParams({status: status})
  });
  await loadProjectDetails(currentProjectId);
}

// 7. ORÇAMENTO FINAL
function renderFinalView() {
  if (!currentProjectData) return;
  const p = currentProjectData.project;
  const mk = currentProjectData.markup_result;
  const w = currentProjectData.weight_result;
  const view = document.getElementById("final-summary-view");

  view.innerHTML = `
    <div style="background: #f8fafc; border: 1px solid var(--border); border-radius: var(--radius); padding: 24px;">
      <div style="display: flex; justify-content: space-between; border-bottom: 2px solid var(--primary); padding-bottom: 12px; margin-bottom: 16px;">
        <div>
          <h2 style="font-size: 1.4rem; color: var(--text-main);">${html(p.name)}</h2>
          <span style="color: var(--text-muted); font-size: 0.85rem;">Código: <b>${html(p.code || "-")}</b> | Cliente: <b>${html(p.client || "RISE")}</b> | Data: <b>${html(p.date)}</b></span>
        </div>
        <div style="text-align: right;">
          <span class="badge ${p.status === 'FINAL' || p.status === 'APROVADO' ? 'badge-success' : 'badge-warning'}" style="font-size: 0.9rem; padding: 6px 14px;">STATUS: ${p.status}</span>
        </div>
      </div>

      <div class="grid-3" style="margin-bottom: 20px;">
        <div style="background: white; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px;">
          <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">CUSTO DIRETO CONHECIDO</span>
          <div style="font-size: 1.8rem; font-weight: 700; color: var(--primary); margin-top: 4px;">R$ ${(mk.cost_mp + mk.cost_mc).toLocaleString("pt-BR", {minimumFractionDigits: 2})}</div>
          <span style="font-size: 0.8rem; color: var(--text-muted);">MP R$ ${mk.cost_mp.toFixed(2)} · Comprados R$ ${mk.cost_mc.toFixed(2)}</span>
        </div>
        <div style="background: white; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px;">
          <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">PESO DA ESTRUTURA EM AÇO</span>
          <div style="font-size: 1.8rem; font-weight: 700; color: var(--text-main); margin-top: 4px;">${w.total_steel_weight.toFixed(3)} kg</div>
          <span style="font-size: 0.8rem; color: var(--text-muted);">Peso validado dos materiais metálicos</span>
        </div>
        <div style="background: white; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px;">
          <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">PESO DO PRODUTO ACABADO</span>
          <div style="font-size: 1.8rem; font-weight: 700; color: var(--text-main); margin-top: 4px;">${w.total_product_weight.toFixed(3)} kg</div>
          <span style="font-size: 0.8rem; color: var(--text-muted);">Total montado com PSAI e acessórios</span>
        </div>
      </div>

      <h4 style="font-size: 0.95rem; margin-bottom: 10px;">Composição de custos (markup preenchido separadamente):</h4>
      <table class="data-table" style="background: white; margin-bottom: 16px;">
        <thead><tr><th>Grupo</th><th>Custo direto conhecido (R$)</th></tr></thead>
        <tbody>
          <tr><td>Matéria-prima (aço e tinta)</td><td>R$ ${mk.cost_mp.toFixed(2)}</td></tr>
          <tr><td>Comprados (PSAI, ferragens e embalagem)</td><td>R$ ${mk.cost_mc.toFixed(2)}</td></tr>
        </tbody>
      </table>
    </div>
  `;
  const missing = currentProjectData.missing_price_ids.length;
  const missingUnits = currentProjectData.missing_unit_ids.length;
  const missingWeights = currentProjectData.missing_weight_ids.length;
  const assemblies = (currentProjectData.unresolved_assembly_ids || []).length;
  const pending = currentProjectData.pending_decisions.filter(x => x.status === 'PENDENTE').length;
  document.getElementById('final-gate-message').textContent = currentProjectData.can_finalize
    ? 'Lista, preços, pendências e pesos prontos para as duas planilhas. Preencha o markup separadamente.'
    : `Versão final bloqueada: ${missing} itens sem preço, ${missingUnits} sem unidade, ${missingWeights} sem peso, ${assemblies} subconjuntos sem composição, ${pending} pendências abertas; conferência de peso: ${w.status_pdf_compare}.`;
  loadVersions();
}

async function loadVersions() {
  const res = await fetch(`/api/projects/${currentProjectId}/versions`);
  const versions = await res.json();
  document.getElementById('versions-list').innerHTML = versions.map(v =>
    `<div>v${v.version_num} — ${html(v.name)} — ${html(v.status)} — ${html(v.created_at)}</div>`).join('') || 'Nenhuma versão salva.';
}

async function saveBudgetVersion(final) {
  if (!currentProjectId) return alert('Selecione um projeto.');
  const raw = document.getElementById('final-price-input').value;
  const res = await fetch(`/api/projects/${currentProjectId}/versions`, {
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({final,final_price:raw ? Number(raw) : null})
  });
  const data = await res.json();
  if (!res.ok) return alert(data.detail || 'Não foi possível guardar a versão.');
  await loadProjectDetails(currentProjectId);
  alert(`Versão ${data.version} guardada: ${data.status}`);
}

async function approveMarkupConfig() {
  if (!currentProjectId) return alert('Selecione um projeto.');
  const res = await fetch(`/api/projects/${currentProjectId}/markup/approve`,{method:'POST'});
  if (!res.ok) return alert('Não foi possível aprovar o markup.');
  await loadProjectDetails(currentProjectId);
}

// 8. REGRAS DE PREÇO
async function loadRulesList() {
  try {
    const res = await fetch("/api/rules");
    const rules = await res.json();
    const tbody = document.getElementById("rules-tbody");
    tbody.innerHTML = "";

    rules.forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${html(r.rule_key)}</code></td>
        <td><b>${html(r.name)}</b><br/><small style="color:var(--text-muted);">${html(r.notes || "")}</small></td>
        <td><span class="badge" style="background:#f1f5f9; color:#475569;">${html(r.category)}</span></td>
        <td><b>${r.unit.startsWith('R$') ? 'R$ ' : ''}${r.value.toFixed(2)}</b></td>
        <td>${html(r.unit)}</td>
        <td><small>${html(r.effective_date)}</small></td>
        <td><small>${html(r.source || "-")}</small></td>
        <td>${r.approved ? '<span class="badge badge-success">Aprovada</span>' : '<span class="badge badge-warning">Candidata</span>'}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="editRulePrompt('${r.rule_key}', ${r.value})">Editar</button>
          ${r.approved ? '' : `<button class="btn btn-sm btn-success" onclick="approveRule('${r.rule_key}', ${r.value})">Aprovar</button>`}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Erro ao carregar regras:", err);
  }
}

async function editRulePrompt(rule_key, currentVal) {
  const newVal = prompt(`Informe o novo valor vigente para ${rule_key}:`, currentVal);
  if (newVal === null || newVal === "") return;
  const num = parseFloat(newVal.replace(',', '.'));
  if (isNaN(num)) return alert("Valor inválido");

  await fetch(`/api/rules/${rule_key}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({value: num, is_active: 1, approved: 0})
  });
  loadRulesList();
}

async function approveRule(key,value) {
  const res=await fetch(`/api/rules/${key}`,{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({value,is_active:1,approved:1})});
  if (!res.ok) return alert('Erro ao aprovar regra.');
  await loadRulesList();
  if (currentProjectId) await loadProjectDetails(currentProjectId);
}

async function searchCatalog() {
  const query=document.getElementById('catalog-query').value.trim();
  const res=await fetch(`/api/catalog?q=${encodeURIComponent(query)}&limit=50`);
  const rows=await res.json();
  document.getElementById('catalog-results').innerHTML=rows.map(r =>
    `<div style="padding:7px;border-bottom:1px solid #ddd">${html(r.description)} — R$ ${r.value.toFixed(2)}/${html(r.unit)} — ${html(r.source)} — ${html(r.effective_date)} `+
    (r.approved ? '<span class="badge badge-success">Aprovado</span>' : `<button class="btn btn-sm btn-secondary" onclick="approveCatalog(${r.id})">Aprovar</button>`)+`</div>`).join('') || 'Nenhum item encontrado.';
}
async function approveCatalog(id) {
  const res=await fetch(`/api/catalog/${id}/approve`,{method:'POST'});
  if (!res.ok) return alert('Erro ao aprovar preço.');
  await searchCatalog();
  if (currentProjectId) await loadProjectDetails(currentProjectId);
}

// EXPORTAÇÕES
async function exportCurrent(format) {
  if (!currentProjectId) return alert("Selecione um projeto antes de exportar.");
  await exportProject(currentProjectId, format);
}

async function exportProject(id, format) {
  try {
    const response = await fetch(`/api/projects/${id}/export/${format}`);
    if (!response.ok) {
      let detail = `Falha na exportação (HTTP ${response.status}).`;
      try {
        const body = await response.json();
        if (body.detail) detail = body.detail;
      } catch (_) {}
      alert(detail);
      return;
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plainName = disposition.match(/filename="?([^";]+)"?/i);
    const filename = encodedName ? decodeURIComponent(encodedName[1])
      : (plainName ? plainName[1] : "orcamento");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    alert(`Não foi possível concluir a exportação: ${error.message || error}`);
  }
}
