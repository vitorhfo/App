// Three read-only budget views. Prices on the agreement screen come from the
// approved script tariff only when the measured geometry and total quantity agree.
const quoteLabels = {
  length: 'Comprimento', width: 'Largura', depth: 'Altura/profundidade',
  thickness: 'Espessura', radius_diam: 'Diâmetro',
  quantity: 'Quantidade total', unit_weight_g: 'Peso acabado'
};
const quoteNumber = value => Number(value).toLocaleString('pt-BR', {maximumFractionDigits: 3});
const quoteMoney = value => value == null ? 'Pendente' :
  `R$ ${Number(value).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

function quoteMeasures(item) {
  const fields = ['length', 'width', 'depth', 'thickness', 'radius_diam'];
  const parts = fields.filter(field => Number(item[field]) > 0)
    .map(field => `${quoteLabels[field]} ${quoteNumber(item[field])} mm`);
  if (Number(item.drawing_length) > 0 && Number(item.wire_allowance_mm) > 0) {
    const index = parts.findIndex(value => value.startsWith('Comprimento'));
    if (index >= 0) parts[index] = `Corte ${quoteNumber(item.drawing_length)} mm · consumo ${quoteNumber(item.length)} mm`;
  }
  return parts.length ? parts.map(html).join(' · ') : 'Cota pendente';
}

function quoteTable(headings, rows, empty) {
  if (!rows.length) return `<p>${html(empty)}</p>`;
  return `<table class="data-table quote-table"><thead><tr>${headings.map(label => `<th>${html(label)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
}

function renderQuoteViews(data) {
  const script = data.script;
  document.getElementById('quote-script-summary').textContent =
    `${script.items.length} peça(s) físicas · custo direto conhecido ${quoteMoney(script.known_cost)} · ${script.missing_prices} sem preço no script. Campos importados da IA foram recuados ao valor anterior nesta visão.`;
  document.getElementById('quote-script-table').innerHTML = quoteTable(
    ['Peça', 'Qtd.', 'Grupo', 'Cotas do script', 'Peso unit.', 'Custo', 'Origem'],
    script.items.map(item => `<tr>
      <td><b>${html(item.description)}</b>${item.ai_imported_fields?.length ? '<br><small>Campos posteriores da IA omitidos</small>' : ''}</td>
      <td>${html(quoteNumber(item.quantity))} ${html(item.unit)}</td>
      <td>${html(item.group_name)}</td><td>${quoteMeasures(item)}</td>
      <td>${Number(item.unit_weight) > 0 ? `${html(quoteNumber(Number(item.unit_weight) * 1000))} g` : 'Pendente'}</td>
      <td>${quoteMoney(item.total_price)}</td><td><small>${sourceLink(item.source_page)}</small></td></tr>`),
    'Nenhuma peça física cadastrada pelo script.');

  const ai = data.ai;
  document.getElementById('quote-ai-summary').textContent =
    `${ai.reviewed_pages}/${ai.total_pages} página(s) com leitura válida · ${ai.items.length} leitura(s) de peças ou variantes. Quantidade local e variantes sem seleção não compõem um total financeiro.`;
  document.getElementById('quote-ai-table').innerHTML = quoteTable(
    ['Leitura da IA', 'Material', 'Medidas', 'Qtd. e escopo', 'Vínculo', 'PDF e evidência'],
    ai.items.map(item => `<tr>
      <td><b>${html(item.description)}</b>${item.item_number ? `<br><small>Código/item ${html(item.item_number)}</small>` : ''}</td>
      <td>${html(item.material || 'Não informado')}</td><td>${quoteMeasures(item)}</td>
      <td>${item.quantity == null ? 'Pendente' : html(quoteNumber(item.quantity))}<br><small>${html(item.quantity_scope)}</small></td>
      <td>${item.script_item_id ? `Item do script #${html(item.script_item_id)}` : 'Sem peça vinculada'}</td>
      <td><small>${sourceLink(item.source_page)} · ${html(item.model)}</small><br><small>${html(item.evidence)}</small></td></tr>`),
    'A IA ainda não concluiu nenhuma leitura válida deste projeto.');

  const agreed = data.agreement;
  document.getElementById('quote-agreement-summary').textContent =
    `${agreed.items.length} peça(s) com alguma informação em comum · ${agreed.fully_confirmed_items}/${agreed.total_script_items} com cotas necessárias e quantidade total conferidas · custo conhecido dessas peças ${quoteMoney(agreed.known_cost)}. Este subtotal não é o orçamento final.`;
  document.getElementById('quote-agreement-table').innerHTML = quoteTable(
    ['Peça', 'Informações que batem', 'Divergências', 'Situação', 'Custo conhecido', 'Origem'],
    agreed.items.map(item => {
      const fields = Object.entries(item.confirmed_fields).map(([key, value]) =>
        `${quoteLabels[key] || key}: ${quoteNumber(value)}${key === 'quantity' ? ' un' : key === 'unit_weight_g' ? ' g' : ' mm'}`);
      return `<tr><td><b>${html(item.description)}</b><br><small>${html(item.group_name)}</small></td>
        <td>${fields.length ? fields.map(html).join('<br>') : 'Nenhuma cota conferida'}</td>
        <td>${item.differing_fields.length ? html(item.differing_fields.map(field => quoteLabels[field] || field).join(', ')) : '—'}</td>
        <td>${item.complete ? '<span class="badge badge-success">Cotas e quantidade conferidas</span>' : '<span class="badge badge-warning">Conferência parcial</span>'}</td>
        <td>${quoteMoney(item.total_price)}</td><td><small>${sourceLink(item.source_page)}</small></td></tr>`;
    }), 'Ainda não há informações independentes coincidentes entre script e IA.');
}

async function loadQuoteViews(projectId) {
  for (const name of ['script', 'ai', 'agreement']) {
    document.getElementById(`quote-${name}-summary`).textContent = 'Carregando conferência...';
  }
  try {
    const response = await fetch(`/api/projects/${projectId}/quote-views`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Falha ao carregar as três visões.');
    if (currentProjectId === projectId) renderQuoteViews(data);
  } catch (error) {
    if (currentProjectId === projectId) {
      for (const name of ['script', 'ai', 'agreement']) {
        document.getElementById(`quote-${name}-summary`).textContent = error.message;
      }
    }
  }
}
