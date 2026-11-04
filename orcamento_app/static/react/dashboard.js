const React = window.React;
const ReactDOM = window.ReactDOM;
const h = React.createElement;
const { useEffect, useMemo, useState } = React;

const navGroups = [
  {
    label: 'ORÇAMENTO',
    items: [
      { id: 'view-projetos', label: 'Projetos', icon: 'grid', needsProject: false },
      { id: 'view-importacao', label: 'Importar arquivos', icon: 'folder', needsProject: true },
      { id: 'view-bom', label: 'Materiais', icon: 'list', needsProject: true },
    ],
  },
  {
    label: 'CONFERÊNCIA',
    items: [
      { id: 'view-peso', label: 'Peso e medidas', icon: 'scale', needsProject: true },
      { id: 'view-custos', label: 'Custos', icon: 'coins', needsProject: true },
      { id: 'view-pendencias', label: 'Pendências', icon: 'warning', needsProject: true },
    ],
  },
  {
    label: 'LEITURAS',
    items: [
      { id: 'view-orc-script', label: 'Leitura do script', icon: 'code', needsProject: true },
      { id: 'view-orc-ia', label: 'Leitura da IA', icon: 'spark', needsProject: true },
      { id: 'view-orc-acordo', label: 'Conferido pelos dois', icon: 'check', needsProject: true },
    ],
  },
  {
    label: 'FINALIZAÇÃO',
    items: [
      { id: 'view-final', label: 'Planilhas', icon: 'download', needsProject: true },
      { id: 'view-regras', label: 'Regras de preço', icon: 'settings', needsProject: false },
    ],
  },
];

const viewTitles = Object.fromEntries(navGroups.flatMap(group =>
  group.items.map(item => [item.id, item.label])));

const iconPaths = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z',
  folder: 'M3 6.5A1.5 1.5 0 0 1 4.5 5H10l2 2h7.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z',
  list: 'M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01',
  scale: 'M12 3v18M5 7h14M5 7l-3 6h6zM19 7l-3 6h6zM8 21h8',
  coins: 'M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3z M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5 M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  warning: 'M12 3 2.8 19a1.3 1.3 0 0 0 1.1 2h16.2a1.3 1.3 0 0 0 1.1-2z M12 9v5M12 17.5h.01',
  code: 'm8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16',
  spark: 'm12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z M19 15l1 2.5 2.5 1-2.5 1L19 22l-1-2.5-2.5-1 2.5-1z',
  check: 'M20 6 9 17l-5-5 M12 22a10 10 0 1 1 0-20 10 10 0 0 1 0 20z',
  download: 'M12 3v12m0 0 5-5m-5 5-5-5M4 17v4h16v-4',
  settings: 'M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.7 2.9-.2-.1a1.7 1.7 0 0 0-1.8.2l-.1.1h-3.4l-.1-.2a1.7 1.7 0 0 0-1.6-1l-.2.1-2.9-1.7.1-.2a1.7 1.7 0 0 0-.2-1.8l-.1-.1v-3.4l.2-.1a1.7 1.7 0 0 0 1-1.6l-.1-.2 1.7-2.9.2.1a1.7 1.7 0 0 0 1.8-.2l.1-.1h3.4l.1.2a1.7 1.7 0 0 0 1.6 1l.2-.1 2.9 1.7-.1.2a1.7 1.7 0 0 0 .2 1.8l.1.1v3.4z',
  menu: 'M4 6h16M4 12h16M4 18h16',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  search: 'm20 20-4.4-4.4M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0z',
  refresh: 'M20 7v5h-5M4 17v-5h5m-3.2-4A7 7 0 0 1 18 6l2 2M4 16l2 2a7 7 0 0 0 12.2-2',
};

function Icon({ name, size = 18 }) {
  return h('svg', { className: 'dash-icon', width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': 'true' },
    h('path', { d: iconPaths[name] || iconPaths.grid }));
}

function statusLabel(status) {
  const key = String(status || '').toUpperCase();
  if (key === 'FINAL' || key === 'CONCLUIDO') return 'Concluído';
  if (key === 'APROVADO') return 'Aprovado';
  if (key === 'EM_REVISAO') return 'Em revisão';
  return 'Preliminar';
}

function statusTone(status) {
  const key = String(status || '').toUpperCase();
  return key === 'FINAL' || key === 'CONCLUIDO' || key === 'APROVADO' ? 'success' :
    key === 'EM_REVISAO' ? 'review' : 'draft';
}

function money(value) {
  return Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function Sidebar({ view, project, mobileOpen, onNavigate, onClose }) {
  return h(React.Fragment, null,
    mobileOpen ? h('button', { className: 'dash-backdrop', type: 'button', onClick: onClose, 'aria-label': 'Fechar menu' }) : null,
    h('aside', { className: `sidebar dash-sidebar${mobileOpen ? ' is-open' : ''}` },
      h('div', { className: 'dash-brand' },
        h('div', { className: 'dash-brand-mark' }, 'O'),
        h('div', null, h('strong', null, 'ORÇA'), h('small', null, 'Orçamento técnico')),
      ),
      project ? h('div', { className: 'dash-current-project' },
        h('span', { className: 'dash-current-label' }, 'PROJETO ABERTO'),
        h('strong', null, project.name),
        h('small', null, [project.client, project.code].filter(Boolean).join(' · ') || 'Sem código'),
      ) : null,
      h('nav', { className: 'nav-menu dash-nav', 'aria-label': 'Navegação principal' },
        navGroups.map(group => h('div', { className: 'dash-nav-group', key: group.label },
          h('div', { className: 'dash-nav-label' }, group.label),
          group.items.map(item => {
            const disabled = item.needsProject && !project;
            return h('button', {
              type: 'button', key: item.id,
              className: `nav-item dash-nav-item${view === item.id ? ' active' : ''}${disabled ? ' is-disabled' : ''}`,
              disabled,
              onClick: () => onNavigate(item.id),
              title: disabled ? 'Abra um projeto para acessar esta tela' : item.label,
            }, h(Icon, { name: item.icon }), h('span', null, item.label),
              item.id === 'view-pendencias' && project?.open_decisions_count > 0 ?
                h('span', { className: 'dash-nav-count' }, project.open_decisions_count) : null);
          }),
        )),
      ),
      h('div', { className: 'dash-sidebar-footer' },
        h('span', { className: 'dash-status-dot' }),
        h('span', null, 'Dados guardados neste computador'),
      ),
    ),
  );
}

function Topbar({ view, project, projects, onMenu, onCreate }) {
  const title = viewTitles[view] || 'Projetos';
  return h('header', { className: 'top-header dash-topbar' },
    h('div', { className: 'dash-topbar-left' },
      h('button', { className: 'dash-menu-button', type: 'button', onClick: onMenu, 'aria-label': 'Abrir menu' }, h(Icon, { name: 'menu' })),
      h('div', { className: 'dash-breadcrumb' },
        h('span', null, project ? 'ORÇAMENTOS' : 'GESTÃO DE PROJETOS'),
        project ? h(React.Fragment, null, h('span', { className: 'dash-breadcrumb-sep' }, '/'), h('strong', null, title)) : null,
        !project ? h('strong', null, title) : null,
      ),
    ),
    h('div', { className: 'header-actions dash-topbar-actions' },
      project ? h(React.Fragment, null,
        h('label', { className: 'dash-project-select-label', htmlFor: 'dash-project-select' }, 'Projeto'),
        h('select', {
          id: 'dash-project-select', className: 'dash-project-select', value: String(project.id),
          onChange: event => window.selectProject?.(Number(event.target.value)),
          'aria-label': 'Selecionar projeto',
        }, projects.map(item => h('option', { key: item.id, value: String(item.id) }, `${item.client || 'RISE'} · ${item.name}`))),
        h('span', { className: `dash-status-chip ${statusTone(project.status)}` }, statusLabel(project.status)),
      ) : h('button', { className: 'dash-button dash-button-primary', type: 'button', onClick: onCreate },
        h('span', { className: 'dash-button-plus' }, '+'), ' Novo projeto'),
    ),
  );
}

function ProjectCard({ project, onOpen }) {
  const missing = Number(project.missing_prices_count || 0);
  const openAssemblies = Number(project.unresolved_assemblies_count || 0);
  return h('article', { className: 'dash-project-card' },
    h('div', { className: 'dash-project-card-top' },
      h('div', { className: 'dash-project-avatar' }, (project.name || 'P').trim().slice(0, 1).toUpperCase()),
      h('span', { className: `dash-status-chip ${statusTone(project.status)}` }, statusLabel(project.status)),
    ),
    h('div', { className: 'dash-project-title-wrap' },
      h('span', { className: 'dash-project-client' }, project.client || 'RISE'),
      h('h3', null, project.name),
      h('p', null, project.code ? `Código ${project.code}` : 'Orçamento sem código'),
    ),
    h('div', { className: 'dash-project-metrics' },
      h('div', null, h('span', null, 'Itens'), h('strong', null, Number(project.items_count || 0).toLocaleString('pt-BR'))),
      h('div', null, h('span', null, 'Peso total'), h('strong', null, `${Number(project.total_weight || 0).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} kg`)),
      h('div', null, h('span', null, 'Custo conhecido'), h('strong', null, money(project.cost_total))),
    ),
    h('div', { className: 'dash-project-footer' },
      h('div', { className: 'dash-project-alerts' },
        missing ? h('span', { className: 'dash-alert-tag warning' }, `${missing} sem preço`) :
          h('span', { className: 'dash-alert-tag good' }, 'Preços preenchidos'),
        openAssemblies ? h('span', { className: 'dash-alert-tag neutral' }, `${openAssemblies} conjuntos para detalhar`) : null,
      ),
      h('button', { className: 'dash-open-project', type: 'button', onClick: () => onOpen(project.id) },
        'Abrir orçamento', h(Icon, { name: 'arrow', size: 16 })),
    ),
  );
}

function ProjectsDashboard({ projects, error, loading, onRetry, onCreate, onOpen }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('todos');
  const filtered = useMemo(() => projects.filter(project => {
    const searchable = `${project.name || ''} ${project.client || ''} ${project.code || ''}`.toLocaleLowerCase('pt-BR');
    const matchesQuery = searchable.includes(query.trim().toLocaleLowerCase('pt-BR'));
    const isComplete = ['FINAL', 'CONCLUIDO', 'APROVADO'].includes(String(project.status || '').toUpperCase());
    return matchesQuery && (filter === 'todos' || (filter === 'concluidos' ? isComplete : !isComplete));
  }), [projects, query, filter]);
  const preliminaries = projects.filter(project => !['FINAL', 'CONCLUIDO', 'APROVADO'].includes(String(project.status || '').toUpperCase())).length;
  const missingPrices = projects.reduce((sum, project) => sum + Number(project.missing_prices_count || 0), 0);
  const totalItems = projects.reduce((sum, project) => sum + Number(project.items_count || 0), 0);

  return h('div', { className: 'dash-projects-page' },
    h('div', { className: 'dash-page-heading' },
      h('div', null,
        h('div', { className: 'dash-eyebrow' }, 'ÁREA DE TRABALHO'),
        h('h1', null, 'Seus projetos'),
        h('p', null, 'Encontre um orçamento, confira os dados e continue de onde parou.'),
      ),
      h('button', { className: 'dash-button dash-button-primary', type: 'button', onClick: onCreate },
        h('span', { className: 'dash-button-plus' }, '+'), ' Criar orçamento'),
    ),
    h('div', { className: 'dash-stat-grid' },
      [
        { label: 'Projetos cadastrados', value: projects.length, note: 'Todos os orçamentos', icon: 'grid', color: 'blue' },
        { label: 'Em andamento', value: preliminaries, note: 'Ainda em revisão', icon: 'list', color: 'amber' },
        { label: 'Itens sem preço', value: missingPrices, note: 'Precisam de tarifa aprovada', icon: 'coins', color: 'rose' },
        { label: 'Itens lidos', value: totalItems, note: 'Somados nos projetos', icon: 'check', color: 'green' },
      ].map(stat => h('div', { className: 'dash-stat-card', key: stat.label },
        h('div', { className: `dash-stat-icon ${stat.color}` }, h(Icon, { name: stat.icon, size: 19 })),
        h('div', null, h('span', null, stat.label), h('strong', null, Number(stat.value).toLocaleString('pt-BR')), h('small', null, stat.note)),
      )),
    ),
    h('div', { className: 'dash-list-heading' },
      h('div', null, h('h2', null, 'Orçamentos'), h('span', null, `${filtered.length} de ${projects.length}`)),
      h('div', { className: 'dash-project-controls' },
        h('label', { className: 'dash-search' }, h(Icon, { name: 'search', size: 17 }),
          h('input', { type: 'search', value: query, onChange: event => setQuery(event.target.value), placeholder: 'Buscar por projeto, cliente ou código', 'aria-label': 'Buscar projetos' })),
        h('div', { className: 'dash-filter-tabs', role: 'group', 'aria-label': 'Filtrar projetos' },
          [['todos', 'Todos'], ['andamento', 'Em andamento'], ['concluidos', 'Concluídos']].map(([key, label]) =>
            h('button', { key, type: 'button', className: filter === key ? 'active' : '', onClick: () => setFilter(key) }, label)),
        ),
      ),
    ),
    error ? h('div', { className: 'dash-empty-state dash-error-state' },
      h('div', { className: 'dash-empty-icon' }, h(Icon, { name: 'refresh', size: 22 })),
      h('h3', null, 'Não foi possível carregar os projetos'),
      h('p', null, error),
      h('button', { className: 'dash-button dash-button-secondary', type: 'button', onClick: onRetry }, 'Tentar novamente'),
    ) : loading ? h('div', { className: 'dash-empty-state dash-loading-state', role: 'status' },
      h('div', { className: 'dash-spinner' }), h('h3', null, 'Carregando projetos'), h('p', null, 'Um momento enquanto buscamos seus orçamentos.'),
    ) : !projects.length ? h('div', { className: 'dash-empty-state' },
      h('div', { className: 'dash-empty-icon' }, h(Icon, { name: 'folder', size: 22 })),
      h('h3', null, 'Nenhum orçamento por aqui ainda'),
      h('p', null, 'Crie um orçamento e importe a pasta do projeto para começar a leitura dos desenhos.'),
      h('button', { className: 'dash-button dash-button-primary', type: 'button', onClick: onCreate }, 'Criar primeiro orçamento'),
    ) : !filtered.length ? h('div', { className: 'dash-empty-state dash-empty-compact' },
      h('h3', null, 'Nenhum projeto encontrado'), h('p', null, 'Tente outro nome, cliente ou filtro.'),
    ) : h('div', { className: 'dash-project-grid' },
      filtered.map(project => h(ProjectCard, { key: project.id, project, onOpen })),
    ),
  );
}

function DashboardApp() {
  const [projects, setProjects] = useState(window.budgetUiState?.projects || []);
  const [project, setProject] = useState(window.budgetUiState?.project || null);
  const [view, setView] = useState(window.budgetUiState?.view || 'view-projetos');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onProjects = event => { setProjects(event.detail || []); setError(''); setLoading(false); };
    const onError = event => { setError(event.detail || 'Erro desconhecido.'); setLoading(false); };
    const onProject = event => setProject(event.detail || null);
    const onView = event => { setView(event.detail || 'view-projetos'); setMobileOpen(false); };
    window.addEventListener('budget:projects', onProjects);
    window.addEventListener('budget:projects-error', onError);
    window.addEventListener('budget:project', onProject);
    window.addEventListener('budget:view', onView);
    if (window.budgetUiState?.projects?.length) setProjects(window.budgetUiState.projects);
    window.loadProjectsList?.();
    return () => {
      window.removeEventListener('budget:projects', onProjects);
      window.removeEventListener('budget:projects-error', onError);
      window.removeEventListener('budget:project', onProject);
      window.removeEventListener('budget:view', onView);
    };
  }, []);

  const navigate = id => { window.switchView?.(id); setMobileOpen(false); };
  const retry = () => { setError(''); setLoading(true); window.loadProjectsList?.(); };
  const createProject = () => window.openNewProjectModal?.();
  const openProject = id => window.selectProject?.(id);

  return h(React.Fragment, null,
    ReactDOM.createPortal(
      h(Sidebar, { view, project, mobileOpen, onNavigate: navigate, onClose: () => setMobileOpen(false) }),
      document.getElementById('react-sidebar-root')),
    ReactDOM.createPortal(
      h(Topbar, { view, project, projects, onMenu: () => setMobileOpen(open => !open), onCreate: createProject }),
      document.getElementById('react-topbar-root')),
    ReactDOM.createPortal(
      h(ProjectsDashboard, { projects, error, loading, onRetry: retry, onCreate: createProject, onOpen: openProject }),
      document.getElementById('react-projects-root')),
  );
}

const appRoot = document.getElementById('react-app-root');
const sidebarRoot = document.getElementById('react-sidebar-root');
const projectsRoot = document.getElementById('react-projects-root');
const topbarRoot = document.getElementById('react-topbar-root');

if (appRoot && sidebarRoot && projectsRoot && topbarRoot && ReactDOM?.createRoot) {
  ReactDOM.createRoot(appRoot).render(h(DashboardApp));
}
