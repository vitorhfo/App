import sqlite3
import json
import os
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT,
        client TEXT,
        date TEXT,
        status TEXT DEFAULT 'PRELIMINAR', -- PRELIMINAR, EM_REVISAO, APROVADO, CONCLUIDO
        folder_path TEXT,
        pdf_root_file TEXT,
        nominal_weight_pdf REAL DEFAULT 0.0,
        nominal_area_pdf REAL DEFAULT 0.0,
        historical_steel_weight REAL DEFAULT 0.0,
        historical_total_weight REAL DEFAULT 0.0,
        tolerance_percent REAL DEFAULT 5.0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        item_num INTEGER,
        description TEXT NOT NULL,
        group_name TEXT NOT NULL, -- Chapa, Arame, Tubo Quadrado/Retangular, Tubo Redondo, Polímero/PSAI, Impressão, Pintura a Pó, Ferragens, Outros Comprados, Embalagem
        item_type TEXT, -- materia_prima, comprado, subconjunto
        material TEXT,
        thickness REAL DEFAULT 0.0, -- mm
        radius_diam REAL DEFAULT 0.0, -- mm
        width REAL DEFAULT 0.0, -- mm
        depth REAL DEFAULT 0.0, -- mm (ou altura)
        length REAL DEFAULT 0.0, -- mm
        drawing_length REAL, -- nominal wire length before welding allowance
        wire_allowance_mm REAL DEFAULT 0.0,
        quantity REAL DEFAULT 1.0,
        unit TEXT DEFAULT 'un', -- un, kg, m, m2
        unit_weight REAL DEFAULT 0.0, -- kg
        total_weight REAL DEFAULT 0.0, -- kg
        finished_unit_weight REAL, -- CAD finished-wire mass before extra cut
        finished_total_weight REAL,
        unit_area REAL DEFAULT 0.0, -- m2
        total_area REAL DEFAULT 0.0, -- m2
        drawing_id TEXT,
        raw_code TEXT,
        finish TEXT,
        printing TEXT DEFAULT '0x0', -- 0x0, 4x0, 4x1, 4x4
        unit_price REAL,
        total_price REAL,
        price_source TEXT,
        source_page TEXT,
        confidence REAL DEFAULT 1.0, -- 0.0 a 1.0
        parent_assembly TEXT,
        mirrored_assembly TEXT, -- counterpart assembly included in quantity
        is_consolidated INTEGER DEFAULT 0,
        is_inferred INTEGER DEFAULT 0,
        pending_issue TEXT,
        observation TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS price_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_key TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL, -- Matéria-Prima, Polímeros, Impressão, Ferragens, Acessórios, Embalagem
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        effective_date TEXT DEFAULT '2026-10-13',
        source TEXT,
        notes TEXT,
        is_active INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS catalog_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        normalized TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        source TEXT NOT NULL,
        effective_date TEXT,
        approved INTEGER DEFAULT 0,
        UNIQUE(normalized, source)
    )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    from reading_reports import ensure_reading_reports
    ensure_reading_reports(conn)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_review_jobs (
        project_id INTEGER NOT NULL,
        path TEXT NOT NULL,
        page INTEGER NOT NULL,
        model TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at REAL NOT NULL DEFAULT 0,
        force INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (project_id, path, page, model),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS wire_variants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        source_page TEXT NOT NULL,
        code TEXT NOT NULL,
        description TEXT NOT NULL,
        nominal TEXT NOT NULL,
        measure_a REAL NOT NULL,
        cut_length REAL NOT NULL,
        diameter REAL NOT NULL,
        material TEXT NOT NULL,
        quantity REAL,
        material_id INTEGER,
        ai_agreement_count INTEGER DEFAULT 0,
        UNIQUE(project_id, source_page, code),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL
    )
    """)
    wire_columns = {row[1] for row in cur.execute('PRAGMA table_info(wire_variants)')}
    if 'material_id' not in wire_columns:
        cur.execute('ALTER TABLE wire_variants ADD COLUMN material_id INTEGER')

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_discovered_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        identity_key TEXT NOT NULL,
        source_page TEXT NOT NULL,
        description TEXT NOT NULL,
        group_name TEXT NOT NULL,
        item_type TEXT NOT NULL,
        material TEXT NOT NULL,
        dimensions_json TEXT NOT NULL,
        evidence TEXT NOT NULL,
        dimension_basis TEXT,
        ready INTEGER NOT NULL DEFAULT 0,
        material_id INTEGER,
        UNIQUE(project_id, identity_key),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS markup_configs (
        project_id INTEGER PRIMARY KEY,
        mo_items TEXT, -- JSON com rateios de MO (efetivo % e padrao %)
        operational_items TEXT, -- JSON com desp. operacionais
        taxes_items TEXT, -- JSON com impostos
        margin_mp REAL DEFAULT 18.0,
        margin_mc REAL DEFAULT 18.0,
        notes TEXT,
        approved INTEGER DEFAULT 0,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS box_configs (
        project_id INTEGER PRIMARY KEY,
        length REAL DEFAULT 880.0,
        width REAL DEFAULT 130.0,
        height REAL DEFAULT 350.0,
        flap_type INTEGER DEFAULT 2, -- 1: Normal, 2: Transpassada
        sheet_type INTEGER DEFAULT 2, -- 1: Onda Baixa (2.09), 2: Folha Simples (5.20), 3: Folha Dupla (5.40)
        custom_sqm_price REAL DEFAULT 0.0,
        calculated_area REAL DEFAULT 0.0,
        calculated_cost REAL DEFAULT 0.0,
        quantity REAL DEFAULT 1.0,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS budget_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        version_num INTEGER NOT NULL,
        name TEXT NOT NULL,
        status TEXT DEFAULT 'PRELIMINAR',
        summary_json TEXT,
        prices_snapshot_json TEXT,
        rules_snapshot_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS material_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        material_id INTEGER NOT NULL,
        before_json TEXT NOT NULL,
        after_json TEXT NOT NULL,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Keep existing local databases intact while adding explicit approval state.
    for table, column, definition in (
        ("price_rules", "approved", "INTEGER DEFAULT 0"),
        ("markup_configs", "approved", "INTEGER DEFAULT 0"),
        ("projects", "final_price", "REAL"),
        ("materials", "item_type", "TEXT"),
        ("materials", "mirrored_assembly", "TEXT"),
        ("materials", "drawing_length", "REAL"),
        ("materials", "wire_allowance_mm", "REAL DEFAULT 0.0"),
        ("materials", "finished_unit_weight", "REAL"),
        ("materials", "finished_total_weight", "REAL"),
    ):
        columns = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    from item_types import infer_item_type
    for row in cur.execute("""SELECT id,description,group_name,drawing_id,thickness,
            radius_diam,width,depth,length,pending_issue FROM materials
            WHERE item_type IS NULL OR item_type=''""").fetchall():
        item_type=infer_item_type(row['description'],row['group_name'],drawing_id=row['drawing_id'],
            has_dimensions=any(row[k] for k in ('thickness','radius_diam','width','depth','length')),
            pending_issue=row['pending_issue'])
        cur.execute('UPDATE materials SET item_type=? WHERE id=?',(item_type,row['id']))
    cur.execute("""UPDATE materials SET unit_price=NULL,total_price=NULL,price_source=''
        WHERE item_type='subconjunto' AND (unit_price IS NOT NULL OR total_price IS NOT NULL)""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        item_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        impact_level TEXT DEFAULT 'MEDIO', -- BAIXO, MEDIO, ALTO
        proposed_action TEXT,
        status TEXT DEFAULT 'PENDENTE', -- PENDENTE, APROVADO, REJEITADO
        approved_by TEXT,
        resolved_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY (item_id) REFERENCES materials(id) ON DELETE SET NULL
    )
    """)

    seed_default_rules(cur)
    cur.execute('''UPDATE materials SET unit_area=width*length/1000000.0,
        total_area=width*length*quantity/1000000.0
        WHERE group_name='Polímero/PSAI' AND item_type='comprado'
        AND COALESCE(unit_area,0)<=0 AND width>0 AND length>0''')
    psai_area_filled=cur.rowcount>0
    from controlv import sync_controlv_rules
    if sync_controlv_rules(cur) or psai_area_filled:
        from pricing import approved_rules, price_item
        rules=approved_rules(conn)
        for row in cur.execute("SELECT * FROM materials WHERE group_name='Polímero/PSAI' AND item_type='comprado'").fetchall():
            item=dict(row)
            if (item.get('price_source') or '').startswith('Ajuste manual aprovado'):
                continue
            value,source=price_item(item,rules,conn)
            cur.execute('UPDATE materials SET unit_price=?,total_price=?,price_source=? WHERE id=?',
                        (value,round(value*(item['quantity'] or 0),2) if value is not None else None,
                         source,item['id']))
    cur.execute("""UPDATE projects SET status='PRELIMINAR',
        notes='Dados demonstrativos antigos; reimportar desenho original para validação. ' || COALESCE(notes,'')
        WHERE status='FINAL' AND notes IN
        ('Orçamento Histórico Validado','Projeto Completo com Múltiplos PDFs, Subconjuntos e PSAI',
         'Ponta de Gôndola Premium com PSAI e Ferragens')""")
    if not cur.execute('SELECT 1 FROM catalog_prices LIMIT 1').fetchone():
        try:
            from pricing import seed_catalog
            seed_catalog(cur)
        except FileNotFoundError:
            pass  # The database remains independent after its initial catalog import.
    # Migrate the existing catalog once; later user edits to approval stay intact.
    if not cur.execute("SELECT 1 FROM app_meta WHERE key='tube_catalog_approved_v1'").fetchone():
        cur.execute("UPDATE catalog_prices SET approved=1 WHERE source LIKE '% / Tubos'")
        cur.execute("INSERT INTO app_meta(key,value) VALUES ('tube_catalog_approved_v1','2026-10-14')")
    conn.commit()
    conn.close()

def seed_default_rules(cur):
    default_rules = [
        # Matéria-prima metálica conforme modelo vazio confirmado pelo usuário.
        ("mp_chapa_aco", "Chapa de Aço Carbono", "Matéria-Prima", 7.02, "R$/kg", "2026-10-14", "Modelo vazio confirmado pelo usuário", "Custo líquido de R$ 7,02/kg", 1),
        ("mp_arame", "Arame BTC Aço Carbono", "Matéria-Prima", 6.34, "R$/kg", "2026-10-14", "Modelo vazio confirmado pelo usuário", "Preço bruto de R$ 6,34/kg", 1),
        ("mp_tubo_acrescimo_ipi", "Tubo Quadrado/Retangular Acréscimo IPI", "Matéria-Prima", 3.25, "%", "2026-10-14", "Modelo vazio confirmado pelo usuário", "Acréscimo de 3,25% sobre preço de compra", 1),
        ("mp_tubo_fator_liquido", "Tubo - Fator Líquido", "Matéria-Prima", 78.75, "%", "2026-10-14", "Modelo vazio confirmado pelo usuário", "Aplicar 0,7875 após IPI", 1),
        ("mp_arame_fator_liquido", "Arame - Fator Líquido", "Matéria-Prima", 78.75, "%", "2026-10-14", "Modelo vazio confirmado pelo usuário", "Aplicar 0,7875 ao valor bruto de R$ 6,34/kg", 1),
        ("mp_tinta_po", "Tinta / Pintura a Pó (Custo Líquido)", "Matéria-Prima", 25.03, "R$/kg", "2026-10-13", "Planilha de Custo / Histórico", "Custo líquido médio com crédito de impostos (bruto ~34,41)", 1),
        ("taxa_consumo_tinta", "Taxa Consumo de Tinta por Área", "Matéria-Prima", 0.22, "kg/m²", "2026-10-13", "Fórmula Histórica Média", "Consumo empírico por metro quadrado de superfície pintada", 1),

        # Ferragens & Fixadores (Regras Vigentes Anotadas)
        ("ferr_pe_nivelador", "Pé Nivelador", "Ferragens", 0.25, "R$/un", "2026-10-13", "Anotações Vigentes", "Anotação aprovada de R$ 0,25/unidade", 1),
        ("ferr_porca_rebite", "Porca Rebite 1/4\"", "Ferragens", 0.25, "R$/un", "2026-10-13", "Anotações Vigentes", "Anotação aprovada de R$ 0,25/unidade", 1),
        ("ferr_manipulo", "Manípulo Padrão 1/4\"", "Ferragens", 0.25, "R$/un", "2026-10-13", "Anotações Vigentes", "Anotação de R$ 0,25 por unidade (modelo padrão)", 1),
        ("ferr_trava_encaixe", "Trava de Encaixe Fêmea", "Ferragens", 0.25, "R$/un", "2026-10-13", "Anotações Vigentes", "Classificar como comprado; R$ 0,25/unidade", 1),
        ("ferr_mini_cunha", "Mini Cunha / Engate Cama", "Ferragens", 0.25, "R$/un", "2026-10-13", "Anotações Vigentes", "Classificar como comprado; R$ 0,25/unidade", 1),
        ("ferr_parafuso_sext", "Parafuso Sextavado 1/4\"", "Ferragens", 1.20, "R$/un", "2026-10-13", "Tabela Histórica", "Parafuso sextavado 1/4\" x 1/2\" ou padrão", 1),
        ("ferr_porca_sext", "Porca Sextavada 1/4\"", "Ferragens", 0.15, "R$/un", "2026-10-13", "Tabela Histórica", "Porca sextavada 1/4\" padrão ou autotravante", 1),
        ("ferr_arruela", "Arruela Lisa 1/4\"", "Ferragens", 0.10, "R$/un", "2026-10-13", "Tabela Histórica", "Arruela lisa 1/4\"", 1),
        ("ferr_rodizio_c_trava", "Rodízio 2\" com Trava", "Ferragens", 7.15, "R$/un", "2026-10-13", "Tabela Histórica", "Rodízio 2 polegadas com freio", 1),
        ("ferr_rodizio_s_trava", "Rodízio 2\" sem Trava", "Ferragens", 9.15, "R$/un", "2026-10-13", "Tabela Histórica", "Rodízio 2 polegadas giratório sem freio", 1),

        # Acessórios (Regras Vigentes Anotadas)
        ("acess_fita_dupla_face", "Fita Dupla Face", "Acessórios", 1.80, "R$/m", "2026-10-13", "Anotações Vigentes", "Anotação aprovada de R$ 1,80 por metro linear", 1),
        ("acess_porta_etiqueta", "Porta Preço / Porta Etiqueta", "Acessórios", 6.80, "R$/m", "2026-10-13", "Anotações Vigentes", "Ambos usam R$ 6,80 por metro linear", 1),

        # Tabela CONTROLV - Polímeros & Chapas Plásticas
        ("pl_psai_branco_10", "PSAI Branco 1,0mm", "Polímeros", 29.40, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PSAI Branco 1mm", 1),
        ("pl_psai_branco_15", "PSAI Branco 1,5mm", "Polímeros", 44.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PSAI Branco 1,5mm", 1),
        ("pl_psai_branco_20", "PSAI Branco 2,0mm", "Polímeros", 58.50, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PSAI Branco 2mm", 1),
        ("pl_psai_cristal_20", "PSAI Cristal 2,0mm", "Polímeros", 64.24, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PSAI Cristal 2mm", 1),
        ("pl_psai_cristal_30", "PSAI Cristal 3,0mm", "Polímeros", 96.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PSAI Cristal 3mm", 1),
        ("pl_psai_leitoso_20", "PSAI Leitoso 2,0mm", "Polímeros", 64.24, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PSAI Leitoso 2mm", 1),
        ("pl_psai_leitoso_100", "PSAI Leitoso 10,0mm", "Polímeros", 115.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PSAI Leitoso 10mm", 1),

        ("pl_acrilico_leit_20", "Acrílico Leitoso 2,0mm", "Polímeros", 106.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de Acrílico Leitoso 2mm", 1),
        ("pl_acrilico_leit_30", "Acrílico Leitoso 3,0mm", "Polímeros", 122.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de Acrílico Leitoso 3mm", 1),
        ("pl_acrilico_crist_20", "Acrílico Cristal 2,0mm", "Polímeros", 97.87, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de Acrílico Cristal 2mm", 1),
        ("pl_acrilico_crist_30", "Acrílico Cristal 3,0mm", "Polímeros", 113.88, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de Acrílico Cristal 3mm", 1),

        ("pl_adesivo_vinil_010", "Adesivo Vinil Branco 0,10mm", "Polímeros", 2.50, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Adesivo vinil para laminação/impressão", 1),
        ("pl_petg_crist_05", "PETG Cristal 0,5mm", "Polímeros", 31.56, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PETG Cristal 0,5mm", 1),
        ("pl_petg_crist_10", "PETG Cristal 1,0mm", "Polímeros", 33.50, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PETG Cristal 1mm", 1),
        ("pl_petg_crist_15", "PETG Cristal 1,5mm", "Polímeros", 34.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Chapa de PETG Cristal 1,5mm", 1),
        ("pl_polionda_30", "Polionda 3,0mm", "Polímeros", 20.32, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Placa de Polionda 3mm", 1),
        ("pl_polionda_40", "Polionda 4,0mm", "Polímeros", 24.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "Placa de Polionda 4mm", 1),

        # Serviço de Impressão Digital (CONTROLV)
        ("imp_digital_face", "Impressão Digital por Face (m²)", "Impressão", 25.00, "R$/m²", "2026-10-13", "Tabela CONTROLV", "R$ 25/m² para 4x0, R$ 50/m² para 4x4", 1),
        ("imp_psai_adicional_4x1", "Acréscimo PSAI 4x1 ou Colorido", "Impressão", 10.0, "%", "2026-10-13", "Tabela CONTROLV", "Acréscimo de 10% sobre valor total da chapa", 1),

        # Embalagem Papelão (Planilha Paramétrica)
        ("cx_onda_baixa", "Caixa Papelão - Onda Baixa", "Embalagem", 2.09, "R$/m²", "2026-10-13", "Orçamento Caixa Papelão", "Preço por m² calculado de papelão onda baixa", 1),
        ("cx_folha_simples", "Caixa Papelão - Folha Simples", "Embalagem", 5.20, "R$/m²", "2026-10-13", "Orçamento Caixa Papelão", "Preço por m² de papelão folha simples", 1),
        ("cx_folha_dupla", "Caixa Papelão - Folha Dupla", "Embalagem", 5.40, "R$/m²", "2026-10-13", "Orçamento Caixa Papelão", "Preço por m² de papelão folha dupla", 1),
    ]

    approved_metal={'mp_chapa_aco','mp_arame','mp_tubo_acrescimo_ipi',
                    'mp_tubo_fator_liquido','mp_arame_fator_liquido'}
    for rule in default_rules:
        cur.execute("""
        INSERT OR IGNORE INTO price_rules 
        (rule_key, name, category, value, unit, effective_date, source, notes, is_active, approved)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*rule,int(rule[0] in approved_metal)))

def get_default_markup_json():
    # Os 20 centros de custo de M.O. / Rateio Fabril
    mo_items = [
        {"name": "Gaiola", "standard_pct": 1.50, "effective_pct": 0.0, "active": False},
        {"name": "Gaiola Expedição", "standard_pct": 1.39, "effective_pct": 0.0, "active": False},
        {"name": "Gancho", "standard_pct": 0.63, "effective_pct": 0.63, "active": True},
        {"name": "Argola", "standard_pct": 0.78, "effective_pct": 0.0, "active": False},
        {"name": "Dobra", "standard_pct": 0.69, "effective_pct": 0.69, "active": True},
        {"name": "Projeção Blue Light", "standard_pct": 3.10, "effective_pct": 0.0, "active": False},
        {"name": "Transporte / Motoristas", "standard_pct": 2.67, "effective_pct": 2.67, "active": True},
        {"name": "Solda Blue Light", "standard_pct": 1.22, "effective_pct": 0.0, "active": False},
        {"name": "Solda Solução", "standard_pct": 1.38, "effective_pct": 1.38, "active": True},
        {"name": "Acabamento", "standard_pct": 0.44, "effective_pct": 0.44, "active": True},
        {"name": "Manutenção", "standard_pct": 0.43, "effective_pct": 0.43, "active": True},
        {"name": "Qualidade - Tratamento", "standard_pct": 0.81, "effective_pct": 0.81, "active": True},
        {"name": "Administrativo", "standard_pct": 1.55, "effective_pct": 1.55, "active": True},
        {"name": "Grau de Dificuldade", "standard_pct": 0.0, "effective_pct": 0.0, "active": False},
        {"name": "Pintura", "standard_pct": 1.83, "effective_pct": 1.83, "active": True},
        {"name": "Expedição", "standard_pct": 1.23, "effective_pct": 1.23, "active": True},
        {"name": "Expedição Volvo", "standard_pct": 0.26, "effective_pct": 0.0, "active": False},
        {"name": "Zincagem e Banho", "standard_pct": 1.76, "effective_pct": 1.76, "active": True},
        {"name": "Viveiro", "standard_pct": 0.56, "effective_pct": 0.0, "active": False},
        {"name": "Corte Arame", "standard_pct": 0.95, "effective_pct": 0.95, "active": True},
    ]

    # As 9 despesas operacionais
    op_items = [
        {"name": "Frotas / Veículos", "standard_pct": 2.45, "effective_pct": 2.45, "active": True},
        {"name": "Bancos / Taxa Financeira", "standard_pct": 6.00, "effective_pct": 2.00, "active": True},
        {"name": "Vendedores / Comissão", "standard_pct": 5.00, "effective_pct": 5.00, "active": True},
        {"name": "Despesas Gerais", "standard_pct": 4.39, "effective_pct": 4.39, "active": True},
        {"name": "Fretes", "standard_pct": 5.00, "effective_pct": 5.00, "active": True},
        {"name": "Prestador de Serviços", "standard_pct": 0.24, "effective_pct": 0.24, "active": True},
        {"name": "Máquinas e Equipamentos", "standard_pct": 0.44, "effective_pct": 0.44, "active": True},
        {"name": "Informática", "standard_pct": 0.05, "effective_pct": 0.05, "active": True},
        {"name": "Taxa Web Charge / Portal", "standard_pct": 4.00, "effective_pct": 0.0, "active": False},
    ]

    # Impostos
    tax_items = [
        {"name": "ICMS", "standard_pct": 18.00, "effective_pct": 12.00, "active": True},
        {"name": "PIS", "standard_pct": 1.65, "effective_pct": 1.65, "active": True},
        {"name": "COFINS", "standard_pct": 7.60, "effective_pct": 7.60, "active": True},
        {"name": "CSLL + IR", "standard_pct": 2.50, "effective_pct": 2.50, "active": True},
        {"name": "IPI", "standard_pct": 5.00, "effective_pct": 0.0, "active": False},
    ]

    return {
        "mo_items": mo_items,
        "operational_items": op_items,
        "tax_items": tax_items,
        "margin_mp": 18.0,
        "margin_mc": 18.0
    }

if __name__ == "__main__":
    init_db()
    print("Database initialized at", DB_PATH)
