import json

def calculate_markup(cost_mp: float, cost_mc: float, steel_weight_kg: float, config: dict):
    """
    Calcula o markup de acordo com o modelo rigoroso de duas bases da empresa:
    - Base Matéria-Prima (com Rateio de Produção M.O.)
    - Base Material Comprado (sem M.O.)
    """
    mo_items = config.get("mo_items", [])
    op_items = config.get("operational_items", [])
    tax_items = config.get("tax_items", [])
    margin_mp = float(config.get("margin_mp", 18.0))
    margin_mc = float(config.get("margin_mc", 18.0))

    # 1. Totalização das alíquotas efetivas
    sum_mo_effective = sum(float(item.get("effective_pct", 0.0)) for item in mo_items if item.get("active", True))
    sum_op_effective = sum(float(item.get("effective_pct", 0.0)) for item in op_items if item.get("active", True))
    sum_tax_effective = sum(float(item.get("effective_pct", 0.0)) for item in tax_items if item.get("active", True))

    # 2. Base e Fator para MATÉRIA-PRIMA
    base_pct_mp = sum_mo_effective + sum_op_effective + sum_tax_effective + margin_mp
    divisor_mp = 100.0 - base_pct_mp
    if divisor_mp <= 0:
        raise ValueError("Markup de matéria-prima inválido: soma das parcelas deve ser menor que 100%")
    fator_mp = 100.0 / divisor_mp
    preco_sugerido_mp = cost_mp * fator_mp

    # Decomposição dos valores em R$ da Matéria-Prima
    mo_breakdown_mp = []
    for item in mo_items:
        eff = float(item.get("effective_pct", 0.0)) if item.get("active", True) else 0.0
        val_rs = (eff / 100.0) * preco_sugerido_mp
        mo_breakdown_mp.append({"name": item.get("name"), "pct": eff, "val": round(val_rs, 2), "active": item.get("active", True)})

    op_breakdown_mp = []
    for item in op_items:
        eff = float(item.get("effective_pct", 0.0)) if item.get("active", True) else 0.0
        val_rs = (eff / 100.0) * preco_sugerido_mp
        op_breakdown_mp.append({"name": item.get("name"), "pct": eff, "val": round(val_rs, 2), "active": item.get("active", True)})

    tax_breakdown_mp = []
    for item in tax_items:
        eff = float(item.get("effective_pct", 0.0)) if item.get("active", True) else 0.0
        val_rs = (eff / 100.0) * preco_sugerido_mp
        tax_breakdown_mp.append({"name": item.get("name"), "pct": eff, "val": round(val_rs, 2), "active": item.get("active", True)})

    val_margem_mp = (margin_mp / 100.0) * preco_sugerido_mp

    # 3. Base e Fator para MATERIAL COMPRADO (SEM M.O.!)
    base_pct_mc = sum_op_effective + sum_tax_effective + margin_mc
    divisor_mc = 100.0 - base_pct_mc
    if divisor_mc <= 0:
        raise ValueError("Markup de material comprado inválido: soma das parcelas deve ser menor que 100%")
    fator_mc = 100.0 / divisor_mc
    preco_sugerido_mc = cost_mc * fator_mc

    # Decomposição dos valores em R$ do Material Comprado
    op_breakdown_mc = []
    for item in op_items:
        eff = float(item.get("effective_pct", 0.0)) if item.get("active", True) else 0.0
        val_rs = (eff / 100.0) * preco_sugerido_mc
        op_breakdown_mc.append({"name": item.get("name"), "pct": eff, "val": round(val_rs, 2)})

    tax_breakdown_mc = []
    for item in tax_items:
        eff = float(item.get("effective_pct", 0.0)) if item.get("active", True) else 0.0
        val_rs = (eff / 100.0) * preco_sugerido_mc
        tax_breakdown_mc.append({"name": item.get("name"), "pct": eff, "val": round(val_rs, 2)})

    val_margem_mc = (margin_mc / 100.0) * preco_sugerido_mc

    # 4. Consolidação Geral
    custo_total = cost_mp + cost_mc
    preco_sugerido_total = preco_sugerido_mp + preco_sugerido_mc

    part_mp = (preco_sugerido_mp / preco_sugerido_total) if preco_sugerido_total > 0 else 0.0
    part_mc = (preco_sugerido_mc / preco_sugerido_total) if preco_sugerido_total > 0 else 0.0
    margem_ponderada_pct = (part_mp * margin_mp) + (part_mc * margin_mc)

    preco_kg_aco = (preco_sugerido_total / steel_weight_kg) if steel_weight_kg > 0 else 0.0

    return {
        "cost_mp": round(cost_mp, 2),
        "cost_mc": round(cost_mc, 2),
        "cost_total": round(custo_total, 2),
        "steel_weight_kg": round(steel_weight_kg, 3),

        # Matéria-Prima
        "sum_mo_pct": round(sum_mo_effective, 2),
        "sum_op_pct": round(sum_op_effective, 2),
        "sum_tax_pct": round(sum_tax_effective, 2),
        "margin_mp_pct": round(margin_mp, 2),
        "base_mp_pct": round(base_pct_mp, 2),
        "divisor_mp": round(divisor_mp, 2),
        "fator_mp": round(fator_mp, 4),
        "preco_sugerido_mp": round(preco_sugerido_mp, 2),
        "val_mo_total_mp": round(sum(i["val"] for i in mo_breakdown_mp), 2),
        "val_op_total_mp": round(sum(i["val"] for i in op_breakdown_mp), 2),
        "val_tax_total_mp": round(sum(i["val"] for i in tax_breakdown_mp), 2),
        "val_margem_mp": round(val_margem_mp, 2),
        "mo_breakdown_mp": mo_breakdown_mp,
        "op_breakdown_mp": op_breakdown_mp,
        "tax_breakdown_mp": tax_breakdown_mp,

        # Material Comprado
        "margin_mc_pct": round(margin_mc, 2),
        "base_mc_pct": round(base_pct_mc, 2),
        "divisor_mc": round(divisor_mc, 2),
        "fator_mc": round(fator_mc, 4),
        "preco_sugerido_mc": round(preco_sugerido_mc, 2),
        "val_op_total_mc": round(sum(i["val"] for i in op_breakdown_mc), 2),
        "val_tax_total_mc": round(sum(i["val"] for i in tax_breakdown_mc), 2),
        "val_margem_mc": round(val_margem_mc, 2),
        "op_breakdown_mc": op_breakdown_mc,
        "tax_breakdown_mc": tax_breakdown_mc,

        # Totais e Indicadores
        "preco_sugerido_total": round(preco_sugerido_total, 2),
        "preco_alternativo_total": round(preco_sugerido_total, 2), # Inicialmente igual, editável pelo usuário
        "part_mp_pct": round(part_mp * 100.0, 1),
        "part_mc_pct": round(part_mc * 100.0, 1),
        "margem_ponderada_pct": round(margem_ponderada_pct, 2),
        "preco_kg_aco": round(preco_kg_aco, 2)
    }
