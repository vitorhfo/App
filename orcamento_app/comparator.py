def analyze_weights(materials_list: list, nominal_pdf_weight: float = 0.0, historical_steel_weight: float = 0.0, historical_total_weight: float = 0.0, tolerance_pct: float = 5.0):
    """
    Realiza a conferência de peso detalhada:
    - Peso por grupo de material
    - Peso da estrutura metálica em aço (Chapas + Tubos + Arames)
    - Peso do produto acabado completo (Aço + PSAI/Polímeros + Ferragens/Rodízios + Embalagem)
    - Comparação com o desenho técnico (PDF) e orçamento histórico
    - Identificação e decomposição das peças que explicam qualquer divergência
    """
    group_weights = {}
    steel_groups = ["Chapa", "Tubo Quadrado/Retangular", "Tubo Redondo", "Arame"]
    
    total_steel_weight = 0.0
    total_product_weight = 0.0
    total_cut_weight = 0.0
    wire_extra_weight = 0.0
    missing_weight_items = []
    
    top_heavy_parts = []

    for mat in materials_list:
        if mat.get('item_type')=='subconjunto':
            continue
        grp = mat.get("group_name", "Outros")
        cut_weight = float(mat.get("total_weight") or 0.0)
        w = (float(mat['finished_total_weight'])
             if grp == 'Arame' and mat.get('finished_total_weight') is not None
             else cut_weight)
        qty = float(mat.get("quantity", 1.0))
        total_cut_weight += cut_weight
        if grp == 'Arame':
            wire_extra_weight += cut_weight-w
        if (mat.get('unit_weight') or 0) <= 0:
            missing_weight_items.append({'id':mat.get('id'),'description':mat.get('description'),
                                         'group':grp,'quantity':qty})
        
        group_weights[grp] = group_weights.get(grp, 0.0) + w
        total_product_weight += w
        
        if grp in steel_groups:
            total_steel_weight += w
            
        top_heavy_parts.append({
            "description": mat.get("description"),
            "group": grp,
            "quantity": qty,
            "unit_weight": mat.get("unit_weight", 0.0),
            "total_weight": round(w, 3),
            "drawing_id": mat.get("drawing_id", "")
        })

    # Ordena as peças mais pesadas
    top_heavy_parts.sort(key=lambda x: x["total_weight"], reverse=True)
    missing_metal_count=sum(item['group'] in steel_groups for item in missing_weight_items)

    # 1. Comparação com o PDF Nominal
    delta_pdf_steel = 0.0
    delta_pdf_total = 0.0
    status_pdf_compare = "OK"
    pdf_alert_message = ""

    # O campo nominal importado é o peso total do conjunto. Nunca mudamos o
    # significado da referência só porque o peso do aço ficou mais próximo.
    ref_weight = nominal_pdf_weight if nominal_pdf_weight > 0 else 0.0
    if ref_weight > 0:
        pdf_target_type = "Produto Completo (Montado)"
        actual_for_pdf = total_product_weight
            
        diff_val = actual_for_pdf - ref_weight
        diff_pct = (abs(diff_val) / ref_weight * 100.0) if ref_weight > 0 else 0.0
        
        if missing_weight_items:
            status_pdf_compare = "INCOMPLETO"
            pdf_alert_message = (f"Soma parcial: {len(missing_weight_items)} itens ainda sem peso "
                                 f"({missing_metal_count} metálicos). "
                                 f"Diferença parcial para o carimbo: {diff_val:+.3f} kg; "
                                 "confira as peças sem peso antes de avaliar a divergência.")
        elif diff_pct > tolerance_pct:
            status_pdf_compare = "DIVERGENCIA"
            pdf_alert_message = f"Diferença de {diff_val:+.3f} kg ({diff_pct:.1f}%) em relação ao PDF ({ref_weight:.3f} kg - {pdf_target_type}). Tolerância configurada: ±{tolerance_pct}%."
        else:
            status_pdf_compare = "OK"
            pdf_alert_message = f"Peso consistente com o PDF dentro da tolerância de ±{tolerance_pct}% ({diff_pct:.1f}% de variação)."
    else:
        pdf_target_type = "Não informado no PDF"
        diff_val = 0.0
        diff_pct = 0.0
        status_pdf_compare = "SEM_REFERENCIA"
        pdf_alert_message = "Desenho técnico sem peso nominal preenchido no carimbo."

    # 2. Comparação com Histórico
    hist_steel_diff = 0.0
    hist_steel_pct = 0.0
    if historical_steel_weight > 0:
        hist_steel_diff = total_steel_weight - historical_steel_weight
        hist_steel_pct = (abs(hist_steel_diff) / historical_steel_weight) * 100.0

    return {
        "group_weights": {k: round(v, 3) for k, v in group_weights.items()},
        "total_steel_weight": round(total_steel_weight, 3),
        "total_product_weight": round(total_product_weight, 3),
        "total_cut_weight": round(total_cut_weight, 3),
        "wire_extra_weight": round(wire_extra_weight, 3),
        "missing_weight_count": len(missing_weight_items),
        "missing_metal_weight_count": missing_metal_count,
        "missing_weight_items": missing_weight_items,
        "nominal_pdf_weight": round(nominal_pdf_weight, 3),
        "historical_steel_weight": round(historical_steel_weight, 3),
        "historical_total_weight": round(historical_total_weight, 3),
        "pdf_target_type": pdf_target_type,
        "delta_pdf_val": round(diff_val, 3),
        "delta_pdf_pct": round(diff_pct, 2),
        "status_pdf_compare": status_pdf_compare,
        "pdf_alert_message": pdf_alert_message,
        "hist_steel_diff": round(hist_steel_diff, 3),
        "hist_steel_pct": round(hist_steel_pct, 2),
        "tolerance_pct": tolerance_pct,
        "top_heavy_parts": top_heavy_parts[:10],
        # Alerta essencial de proteção contra comparação indevida
        "warning_note": "O peso do carimbo corresponde ao produto montado. O consumo de arame para corte inclui 20 mm extras por peça; esse excedente entra no custo, mas não no peso do produto pronto. A conferência é parcial enquanto houver itens sem peso."
    }
