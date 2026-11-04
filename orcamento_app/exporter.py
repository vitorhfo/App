import os
from html import escape
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from config import EXPORTS_DIR

def export_budget_pdf(project: dict, materials: list, markup_res: dict, weight_res: dict, filename: str = None, pending_decisions: list = None):
    """
    Gera um PDF formal e elegante do orçamento final usando ReportLab.
    """
    if not filename:
        p_name = "".join(c for c in project.get("name", "orcamento") if c.isalnum() or c in ("-", "_")).strip()
        filename = os.path.join(EXPORTS_DIR, f"Orcamento_{p_name}.pdf")
        
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=6
    )
    cell_style = ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#334155")
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0f172a")
    )

    story = []

    # Cabeçalho
    status_label = project.get("status", "PRELIMINAR")
    status_color = "#16a34a" if status_label == "FINAL" or status_label == "APROVADO" else "#d97706"
    
    header_data = [
        [
            Paragraph(f"<b>MEMORIAL DE ORÇAMENTO INDUSTRIAL</b><br/><font color='#64748b' size=9>PROJETOS DE DISPLAYS & MATERIAIS DE PDV</font>", title_style),
            Paragraph(f"<font color='{status_color}'><b>STATUS: {status_label}</b></font><br/><font size=8 color='#64748b'>Emissão: {project.get('date', '2026-10-13')}</font>", ParagraphStyle("Status", parent=cell_bold, alignment=2))
        ]
    ]
    t_head = Table(header_data, colWidths=[360, 160])
    t_head.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_head)
    story.append(Spacer(1, 10))
    if status_label != 'FINAL':
        story.append(Paragraph(
            f"<b>PRELIMINAR:</b> {project.get('missing_prices_count',0)} item(ns) sem preço e "
            f"{project.get('missing_units_count',0)} sem unidade, "
            f"{project.get('missing_weights_count',0)} sem peso, "
            f"{project.get('unresolved_assemblies_count',0)} subconjunto(s) sem composição, "
            f"{project.get('open_decisions_count',0)} decisão(ões) pendente(s). "
            "Valores abaixo representam somente parcelas conhecidas e não são preço final.",
            ParagraphStyle('PreliminarNotice',parent=cell_style,textColor=colors.HexColor('#b45309'),spaceAfter=10)))

    # Dados do Projeto
    proj_info_data = [
        [
            Paragraph(f"<b>Projeto:</b> {escape(str(project.get('name') or ''))}", cell_style),
            Paragraph(f"<b>Código:</b> {escape(str(project.get('code') or '-'))}", cell_style),
            Paragraph(f"<b>Cliente:</b> {escape(str(project.get('client') or 'RISE'))}", cell_style),
        ]
    ]
    t_proj = Table(proj_info_data, colWidths=[240, 140, 140])
    t_proj.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#e2e8f0")),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_proj)
    story.append(Spacer(1, 12))

    # Resumo Financeiro & Formação de Preço (Duas Bases)
    story.append(Paragraph("1. FORMAÇÃO DE PREÇO E RATEIOS (DUAS BASES)", section_style))
    
    resumo_data = [
        [
            Paragraph("<b>Base de Formação</b>", cell_bold),
            Paragraph("<b>Custo Direto (R$)</b>", cell_bold),
            Paragraph("<b>Rateio M.O.</b>", cell_bold),
            Paragraph("<b>Desp. Operac.</b>", cell_bold),
            Paragraph("<b>Impostos</b>", cell_bold),
            Paragraph("<b>Margem</b>", cell_bold),
            Paragraph("<b>Fator MK</b>", cell_bold),
            Paragraph("<b>Preço Venda (R$)</b>", cell_bold),
        ],
        [
            Paragraph("Matéria-Prima (Metal + Tinta)", cell_style),
            Paragraph(f"R$ {markup_res.get('cost_mp', 0):,.2f}", cell_style),
            Paragraph(f"{markup_res.get('sum_mo_pct', 0):.2f}%", cell_style),
            Paragraph(f"{markup_res.get('sum_op_pct', 0):.2f}%", cell_style),
            Paragraph(f"{markup_res.get('sum_tax_pct', 0):.2f}%", cell_style),
            Paragraph(f"{markup_res.get('margin_mp_pct', 0):.2f}%", cell_style),
            Paragraph(f"{markup_res.get('fator_mp', 0):.4f}", cell_style),
            Paragraph(f"R$ {markup_res.get('preco_sugerido_mp', 0):,.2f}", cell_bold),
        ],
        [
            Paragraph("Material Comprado (PSAI, Ferragens, Cx)", cell_style),
            Paragraph(f"R$ {markup_res.get('cost_mc', 0):,.2f}", cell_style),
            Paragraph("0,00% (Isento)", cell_style),
            Paragraph(f"{markup_res.get('sum_op_pct', 0):.2f}%", cell_style),
            Paragraph(f"{markup_res.get('sum_tax_pct', 0):.2f}%", cell_style),
            Paragraph(f"{markup_res.get('margin_mc_pct', 0):.2f}%", cell_style),
            Paragraph(f"{markup_res.get('fator_mc', 0):.4f}", cell_style),
            Paragraph(f"R$ {markup_res.get('preco_sugerido_mc', 0):,.2f}", cell_bold),
        ],
        [
            Paragraph("<b>TOTAL CONSOLIDADO</b>", cell_bold),
            Paragraph(f"<b>R$ {markup_res.get('cost_total', 0):,.2f}</b>", cell_bold),
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph(f"<b>{markup_res.get('margem_ponderada_pct', 0):.2f}% (Pond.)</b>", cell_bold),
            Paragraph("-", cell_style),
            Paragraph(f"<b>R$ {markup_res.get('preco_sugerido_total', 0):,.2f}</b>", ParagraphStyle("TotPreco", parent=cell_bold, textColor=colors.HexColor("#0284c7"))),
        ]
    ]

    t_resumo = Table(resumo_data, colWidths=[130, 65, 50, 50, 45, 55, 45, 80])
    t_resumo.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_resumo)
    if project.get('status') == 'FINAL' and project.get('final_price') is not None:
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>PREÇO FINAL APROVADO: R$ {project['final_price']:,.2f}</b>", cell_bold))
    story.append(Spacer(1, 12))

    # Conferência de Pesos
    story.append(Paragraph("2. CONFERÊNCIA RIGOROSA DE PESO", section_style))
    weight_table_data = [
        [
            Paragraph("<b>Indicador de Peso</b>", cell_bold),
            Paragraph("<b>Peso Calculado (kg)</b>", cell_bold),
            Paragraph("<b>Referência PDF / Histórico (kg)</b>", cell_bold),
            Paragraph("<b>Divergência / Status</b>", cell_bold),
        ],
        [
            Paragraph("Estrutura Metálica em Aço", cell_style),
            Paragraph(f"{weight_res.get('total_steel_weight', 0):.3f} kg", cell_bold),
            Paragraph(f"Histórico: {weight_res.get('historical_steel_weight', 0):.3f} kg", cell_style),
            Paragraph(f"Δ Histórico: {weight_res.get('hist_steel_diff', 0):+.3f} kg ({weight_res.get('hist_steel_pct', 0):.1f}%)", cell_style),
        ],
        [
            Paragraph("Produto Completo Acabado", cell_style),
            Paragraph(f"{weight_res.get('total_product_weight', 0):.3f} kg", cell_bold),
            Paragraph(f"Carimbo PDF: {weight_res.get('nominal_pdf_weight', 0):.3f} kg", cell_style),
            Paragraph(f"Status: {weight_res.get('status_pdf_compare')} ({weight_res.get('delta_pdf_pct', 0):.1f}%)", cell_style),
        ],
        [
            Paragraph("Preço por kg da Estrutura em Aço", cell_style),
            Paragraph(f"R$ {markup_res.get('preco_kg_aco', 0):.2f} / kg", cell_bold),
            Paragraph(f"Tolerância Configurada: ±{weight_res.get('tolerance_pct', 5.0)}%", cell_style),
            Paragraph("Conferir pesos antes da aprovação", cell_style),
        ]
    ]
    t_weight = Table(weight_table_data, colWidths=[160, 110, 130, 120])
    t_weight.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_weight)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<i>Nota Técnica: {escape(str(weight_res.get('warning_note') or ''))}</i>", ParagraphStyle("Note", parent=cell_style, fontSize=7, textColor=colors.HexColor("#64748b"))))
    story.append(Spacer(1, 14))

    # Lista de Materiais Resumida
    story.append(Paragraph("3. LISTA DE MATERIAIS CONSOLIDADA (BOM)", section_style))
    bom_headers = [
        Paragraph("<b>Item</b>", cell_bold),
        Paragraph("<b>Descrição / Especificação</b>", cell_bold),
        Paragraph("<b>Tipo / Grupo</b>", cell_bold),
        Paragraph("<b>Qtd</b>", cell_bold),
        Paragraph("<b>Peso Tot (kg)</b>", cell_bold),
        Paragraph("<b>Unitário (R$)</b>", cell_bold),
        Paragraph("<b>Total (R$)</b>", cell_bold),
    ]
    bom_rows = [bom_headers]
    for m in materials:
        bom_rows.append([
            Paragraph(str(m.get("item_num", "")), cell_style),
            Paragraph(f"{escape(str(m.get('description') or ''))}<br/><font size=6 color='#64748b'>{escape(str(m.get('material') or ''))} | Cód: {escape(str(m.get('drawing_id') or '-'))}</font>", cell_style),
            Paragraph(escape({'materia_prima':'Matéria-prima','comprado':'Comprado','subconjunto':'Subconjunto'}.get(m.get('item_type'),'Item'))+'<br/>'+escape(str(m.get("group_name") or "")), cell_style),
            Paragraph(f"{m.get('quantity')} {m.get('unit', 'un')}", cell_style),
            Paragraph('—' if m.get('item_type')=='subconjunto' else f"{m.get('total_weight', 0):.3f}", cell_style),
            Paragraph('—' if m.get('item_type')=='subconjunto' else f"R$ {m['unit_price']:.2f}" if m.get('unit_price') is not None else "PENDENTE", cell_style),
            Paragraph('—' if m.get('item_type')=='subconjunto' else f"R$ {m['total_price']:.2f}" if m.get('total_price') is not None else "PENDENTE", cell_bold),
        ])

    t_bom = Table(bom_rows, colWidths=[25, 205, 95, 45, 55, 45, 50], repeatRows=1)
    t_bom.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f8fafc")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_bom)
    open_issues=[x for x in (pending_decisions or []) if x.get('status')=='PENDENTE']
    if open_issues:
        story.append(Spacer(1, 14))
        story.append(Paragraph('4. DECISÕES PENDENTES',section_style))
        for issue in open_issues:
            label=escape(str(issue.get('title') or 'Pendência'))
            desc=escape(str(issue.get('description') or ''))
            story.append(Paragraph(f'<b>{label}:</b> {desc}',cell_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    return filename

def export_budget_xlsx(project: dict, materials: list, markup_res: dict, weight_res: dict, filename: str = None, pending_decisions: list = None):
    """
    Exporta a pasta de trabalho completa com múltiplas abas auditadas no formato Excel (.xlsx).
    """
    if not filename:
        p_name = "".join(c for c in project.get("name", "orcamento") if c.isalnum() or c in ("-", "_")).strip()
        filename = os.path.join(EXPORTS_DIR, f"Orcamento_{p_name}.xlsx")

    wb = openpyxl.Workbook()
    
    # 1. Aba Resumo Executivo
    ws_resumo = wb.active
    ws_resumo.title = "Resumo Executivo"
    ws_resumo["A1"] = "ORÇAMENTO DE PROJETO - VISÃO EXECUTIVA"
    ws_resumo["A1"].font = Font(size=14, bold=True, color="1E293B")
    
    ws_resumo["A3"] = "Projeto:"
    ws_resumo["B3"] = project.get("name")
    ws_resumo["A4"] = "Código:"
    ws_resumo["B4"] = project.get("code")
    ws_resumo["A5"] = "Cliente:"
    ws_resumo["B5"] = project.get("client")
    ws_resumo["A6"] = "Data:"
    ws_resumo["B6"] = project.get("date")
    ws_resumo["A7"] = "Status:"
    ws_resumo["B7"] = project.get("status")

    ws_resumo["A9"] = "PREÇO DE VENDA SUGERIDO TOTAL (R$):"
    ws_resumo["B9"] = markup_res.get("preco_sugerido_total", 0.0)
    ws_resumo["A9"].font = Font(bold=True)
    ws_resumo["B9"].font = Font(bold=True, size=12, color="0284C7")
    ws_resumo["A15"] = "Preço final aprovado (R$):"
    ws_resumo["B15"] = project.get("final_price") if project.get("status") == "FINAL" else None

    ws_resumo["A10"] = "Custo Total Direto (R$):"
    ws_resumo["B10"] = markup_res.get("cost_total", 0.0)

    ws_resumo["A11"] = "Margem Ponderada Efetiva (%):"
    ws_resumo["B11"] = f"{markup_res.get('margem_ponderada_pct', 0.0):.2f}%"

    ws_resumo["A12"] = "Peso da Estrutura em Aço (kg):"
    ws_resumo["B12"] = weight_res.get("total_steel_weight", 0.0)

    ws_resumo["A13"] = "Preço por kg da Estrutura Metálica (R$/kg):"
    ws_resumo["B13"] = markup_res.get("preco_kg_aco", 0.0)

    ws_pend = wb.create_sheet(title="Pendências")
    ws_pend.append(["Situação", "Item", "Descrição", "Motivo", "Página de origem"])
    for m in materials:
        if m.get('pending_issue') or (m.get('item_type')!='subconjunto' and m.get('unit_price') is None):
            reason='; '.join(x for x in (m.get('pending_issue'), 'Preço não aprovado' if m.get('item_type')!='subconjunto' and m.get('unit_price') is None else '') if x)
            ws_pend.append(['PENDENTE',m.get('item_num'),m.get('description'),reason,m.get('source_page')])
    for issue in pending_decisions or []:
        ws_pend.append([issue.get('status'),'',issue.get('title'),issue.get('description'),''])

    # 2. Aba Lista de Materiais Completa (BOM)
    ws_bom = wb.create_sheet(title="Lista de Materiais (BOM)")
    headers = [
        "Item", "Quantidade", "Descrição", "Grupo", "Tipo", "Material", "Espessura (mm)",
        "Raio/Diâmetro (mm)", "Largura (mm)", "Profundidade (mm)", "Comprimento (mm)",
        "ID Desenho", "Peso Unit (kg)", "Peso Total (kg)", "Área Unit (m²)", "Área Total (m²)",
        "Acabamento", "Impressão", "Preço Unit (R$)", "Preço Total (R$)", "Fonte Preço",
        "Página Origem", "Conjunto Pai", "Confiança Leitura", "Observação"
    ]
    ws_bom.append(headers)
    for col_idx in range(1, len(headers) + 1):
        cell = ws_bom.cell(1, col_idx)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")

    for m in materials:
        ws_bom.append([
            m.get("item_num"),
            m.get("quantity"),
            m.get("description"),
            m.get("group_name"),
            m.get("item_type"),
            m.get("material"),
            m.get("thickness"),
            m.get("radius_diam"),
            m.get("width"),
            m.get("depth"),
            m.get("length"),
            m.get("drawing_id"),
            m.get("unit_weight"),
            m.get("total_weight"),
            m.get("unit_area"),
            m.get("total_area"),
            m.get("finish"),
            m.get("printing"),
            None if m.get('item_type')=='subconjunto' else m.get("unit_price"),
            None if m.get('item_type')=='subconjunto' else m.get("total_price"),
            m.get("price_source"),
            m.get("source_page"),
            m.get("parent_assembly"),
            m.get("confidence"),
            m.get("observation")
        ])

    # 3. Aba Fator Markup e Formação
    ws_mk = wb.create_sheet(title="Memória Markup")
    ws_mk.append(["Componente", "Matéria-Prima (%)", "Matéria-Prima (R$)", "Material Comprado (%)", "Material Comprado (R$)"])
    ws_mk.append(["Custo Direto Base", "-", markup_res.get("cost_mp", 0), "-", markup_res.get("cost_mc", 0)])
    ws_mk.append(["Rateio Produção M.O.", f"{markup_res.get('sum_mo_pct', 0):.2f}%", markup_res.get("val_mo_total_mp", 0), "0,00%", 0.0])
    ws_mk.append(["Despesas Operacionais", f"{markup_res.get('sum_op_pct', 0):.2f}%", markup_res.get("val_op_total_mp", 0), f"{markup_res.get('sum_op_pct', 0):.2f}%", markup_res.get("val_op_total_mc", 0)])
    ws_mk.append(["Impostos", f"{markup_res.get('sum_tax_pct', 0):.2f}%", markup_res.get("val_tax_total_mp", 0), f"{markup_res.get('sum_tax_pct', 0):.2f}%", markup_res.get("val_tax_total_mc", 0)])
    ws_mk.append(["Margem de Lucro", f"{markup_res.get('margin_mp_pct', 0):.2f}%", markup_res.get("val_margem_mp", 0), f"{markup_res.get('margin_mc_pct', 0):.2f}%", markup_res.get("val_margem_mc", 0)])
    ws_mk.append(["Fator Divisor Markup", markup_res.get("fator_mp", 0), "-", markup_res.get("fator_mc", 0), "-"])
    ws_mk.append(["PREÇO SUGERIDO", "-", markup_res.get("preco_sugerido_mp", 0), "-", markup_res.get("preco_sugerido_mc", 0)])

    # Ajuste automático de largura de colunas
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = min(40, max(max_len + 3, 10))

    wb.save(filename)
    return filename

def export_budget_csv(materials: list, filename: str = None):
    """
    Exporta a lista de materiais em formato CSV delimitado por ponto-e-vírgula.
    """
    if not filename:
        filename = os.path.join(EXPORTS_DIR, "Lista_Materiais.csv")
    
    import csv
    headers = ["Item", "Quantidade", "Unidade", "Descricao", "Grupo", "Tipo", "Material",
        "Espessura_mm", "Diametro_mm", "Largura_mm", "Profundidade_mm", "Comprimento_mm",
        "Peso_Unit_kg", "Peso_Total_kg", "Area_Unit_m2", "Area_Total_m2",
        "Preco_Unit_R$", "Preco_Total_R$", "Fonte_Preco", "Origem", "Conjunto_Pai", "Pendencia"]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)
        for m in materials:
            writer.writerow([
                m.get("item_num"),
                m.get("quantity"),
                m.get("unit"),
                m.get("description"),
                m.get("group_name"),
                m.get("item_type"),
                m.get("material"),
                m.get("thickness"),
                m.get("radius_diam"),
                m.get("width"),
                m.get("depth"),
                m.get("length"),
                m.get("unit_weight"),
                m.get("total_weight"),
                m.get("unit_area"),
                m.get("total_area"),
                None if m.get('item_type')=='subconjunto' else m.get("unit_price"),
                None if m.get('item_type')=='subconjunto' else m.get("total_price"),
                m.get("price_source"),
                m.get("source_page"),
                m.get("parent_assembly"),
                m.get("pending_issue")
            ])
    return filename
