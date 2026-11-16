"""
gestores.py — "Resumo CMAP - Ocupação prédios" por gestor (coluna GERENCIA do forecast).

Uma coluna por reserva do CMAP (MAS + local), com as mesmas linhas do quadro:

  Operação  HC's total (MOP), HCs manhã/tarde (só frentes 6H20), HCs home office,
            PA's ocupadas (regra do forecast.py), PA's disponíveis = reservadas no CMAP
            (PRODUCAGENT-DIR) e % ocupação
  Staff     supervisores/coordenadores, plan/WFM, qualidade, gerentes/diretores
            (digitados na tela; se estiverem vazios, usamos o STAFF do forecast),
            PA's disponíveis = reservadas no CMAP (TEAMLEADER-DIR) e % ocupação
  Total     posições ocupadas, disponíveis e % de ocupação geral
"""
import re
from collections import defaultdict

import banco
import forecast
import meses
import subir

# Nome curto do prédio, como no quadro ("M3 - 2º").
CURTOS = {
    "BR-SAO-TAGIP": "BF4", "BR-BAR-ARAGU": "BAR", "BR-CUR-JOSEL-01": "JL1",
    "BR-CUR-JOSEL-02": "JL2", "BR-CUR-JOSEL-03": "JL3", "BR-CUR-MALDE-01": "M2",
    "BR-CUR-MALDE-02": "M3", "BR-PON-RUASE": "PG", forecast.LOCAL_HOME: "HO",
}
CATEGORIAS_STAFF = [
    ("supervisores", "Staff - Supervisores / Coordenadores"),
    ("plan_wfm", "Staff - Plan / WFM"),
    ("qualidade", "Staff - Qualidade"),
    ("gerentes", "Staff - Gerentes / Diretores"),
]
# Faixa "boa" de ocupação: 90% a 100%. Abaixo sobra PA; acima falta PA.
META_MIN, META_MAX = 0.90, 1.00


def andar_curto(andar) -> str:
    """'2ª' -> '2º', 3 -> '3º', 'TORRE A - 2ª' -> 'Torre A - 2º', 'HOME OFFICE' -> 'HO'."""
    texto = str(andar or "").strip()
    if "home" in forecast.normalizar(texto):
        return "HO"
    texto = re.sub(r"(\d+)\s*[ªº°]?", r"\1º", texto)
    return texto.title().replace("ºº", "º")


def _pct(ocupadas, disponiveis):
    return ocupadas / disponiveis if disponiveis else None


def faixa(pct) -> str:
    """Classe de cor do %: ok (90–100%), sobra (< 90%), falta (> 100%)."""
    if pct is None:
        return ""
    return "falta" if pct > META_MAX else "ok" if pct >= META_MIN else "sobra"


def _reservado(project_id, location_id, mes: meses.Mes):
    """PAs reservadas no CMAP (controle) neste mês: (agentes, staff)."""
    r = banco.db().execute(
        """SELECT a.dept_code, SUM(a.qtd) AS q FROM assentos a
           JOIN reservas r ON r.id = a.reserva_id
           WHERE r.project_id = ? AND r.location_id = ? AND r.status != 'Cancelado'
             AND a.mes = ? GROUP BY a.dept_code""",
        (project_id, location_id, mes.chave)).fetchall()
    q = {x["dept_code"]: x["q"] for x in r}
    return q.get(forecast.DEPT_AGENTE, 0), q.get(forecast.DEPT_STAFF, 0)


def _detalhes():
    return {(d["project_id"], d["location_id"]): d
            for d in banco.db().execute("SELECT * FROM detalhe_reserva")}


def visao(mes: meses.Mes):
    """
    Devolve [{"gerente", "colunas": [...], "total": {...}}], um bloco por gestor.
    """
    frentes = subir.frentes_salvas()
    de_para = subir.de_para()
    ativos = {l["location_id"] for l in banco.locais(somente_ativos=True)}
    detalhes = _detalhes()

    por_gerente = defaultdict(list)
    for f in frentes:
        por_gerente[f.get("gerencia") or "(sem gestor)"].append(f)

    blocos = []
    for gerente in sorted(por_gerente):
        lista = por_gerente[gerente]
        # PAs pela regra, calculadas só com as frentes deste gestor
        calc = forecast.calcular(lista, de_para, [mes], lambda l: l in ativos)

        # HCs brutos por coluna (MAS + local)
        brutos = defaultdict(lambda: {"hc": 0.0, "manha": 0.0, "tarde": 0.0, "home": 0.0,
                                      "andares": set(), "contas": set(), "lobs": set()})
        for f in lista:
            dp = de_para.get(f["lob"])
            v = f["valores"].get(mes.chave)
            if not dp or not dp.get("project_id") or not v or not f["location_id"]:
                continue
            home = min(v["home"], v["mop"])
            if f["location_id"] == forecast.LOCAL_HOME:
                destinos = [(forecast.LOCAL_HOME, v["mop"], 0, 0, v["mop"])]
            else:
                meio = f["fator"] == 2                  # manhã/tarde só nas frentes 6H20
                destinos = [(f["location_id"], v["mop"], v.get("ic_manha", 0) if meio else 0,
                             v.get("ic_tarde", 0) if meio else 0, home)]
                if home:
                    destinos.append((forecast.LOCAL_HOME, home, 0, 0, home))
            for loc, hc, manha, tarde, ho in destinos:
                b = brutos[(dp["project_id"], loc)]
                b["hc"] += hc
                b["manha"] += manha
                b["tarde"] += tarde
                b["home"] += ho
                b["andares"].add(andar_curto(f["andar"]) if loc == f["location_id"] else "HO")
                b["contas"].add((dp.get("cliente") or f["conta"]).upper())
                b["lobs"].add(f["lob"])

        colunas = []
        for chave, b in brutos.items():
            if chave not in calc:                        # local que não acompanho
                continue
            project_id, location_id = chave
            res_ag, res_st = _reservado(project_id, location_id, mes)
            d = detalhes.get(chave)
            staff_digitado = {k: (d[k] if d else 0) for k, _ in CATEGORIAS_STAFF}
            staff_ocup = sum(staff_digitado.values()) or calc[chave]["staff"].get(mes.chave, 0)
            ag_ocup = calc[chave]["agentes"].get(mes.chave, 0)
            andares = sorted(a for a in b["andares"] if a != "HO") or ["HO"]
            colunas.append({
                "project_id": project_id, "location_id": location_id,
                "conta": " / ".join(sorted(b["contas"])),
                "site": f"{CURTOS.get(location_id, location_id)} - {', '.join(andares)}"
                        if location_id != forecast.LOCAL_HOME else "Home Office",
                "particularidades": d["particularidades"] if d else "",
                "lobs": sorted(b["lobs"]),
                "hc": round(b["hc"]), "manha": round(b["manha"]), "tarde": round(b["tarde"]),
                "home": round(b["home"]),
                "ag_ocup": ag_ocup, "ag_disp": res_ag, "ag_pct": _pct(ag_ocup, res_ag),
                "staff": staff_digitado, "staff_do_forecast": not sum(staff_digitado.values()),
                "st_ocup": staff_ocup, "st_disp": res_st, "st_pct": _pct(staff_ocup, res_st),
                "tot_ocup": ag_ocup + staff_ocup, "tot_disp": res_ag + res_st,
            })
        if not colunas:
            continue
        # mesma conta em mais de um prédio vira "CARREFOUR 1", "CARREFOUR 2"...
        colunas.sort(key=lambda c: (c["conta"], c["location_id"] == forecast.LOCAL_HOME, c["site"]))
        repetidas = defaultdict(int)
        for c in colunas:
            repetidas[c["conta"]] += 1
        contador = defaultdict(int)
        for c in colunas:
            c["tot_pct"] = _pct(c["tot_ocup"], c["tot_disp"])
            if repetidas[c["conta"]] > 1:
                contador[c["conta"]] += 1
                c["titulo"] = f"{c['conta']} {contador[c['conta']]}"
            else:
                c["titulo"] = c["conta"]

        total = {k: sum(c[k] for c in colunas) for k in
                 ("hc", "manha", "tarde", "home", "ag_ocup", "ag_disp", "st_ocup", "st_disp",
                  "tot_ocup", "tot_disp")}
        total["staff"] = {k: sum(c["staff"][k] for c in colunas) for k, _ in CATEGORIAS_STAFF}
        for p in ("ag", "st", "tot"):
            total[f"{p}_pct"] = _pct(total[f"{p}_ocup"], total[f"{p}_disp"])
        blocos.append({"gerente": gerente, "colunas": colunas, "total": total})
    return blocos


def gerentes():
    return [g["gerencia"] for g in banco.db().execute(
        "SELECT DISTINCT fr.gerencia FROM frentes fr JOIN forecast f ON f.lob = fr.lob "
        "WHERE fr.gerencia != '' ORDER BY fr.gerencia")]
