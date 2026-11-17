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
# Linhas de staff do CMAP (Dept Code) em cada categoria do quadro.
# Só entram códigos DIRETOS (com "DIR" no código, sem "INDIR"): pedido da Anna,
# "no máximo o direto". Ex.: ADMINFACILITIES, HRGENERALIST, OPERATION-INDIR ficam de fora.
PALAVRAS_STAFF = [
    ("qualidade", ("QUAL", "TRAIN", "TRAN", "AUDIT", "EVALU")),   # qualidade, treinamento, monitoria
    ("plan_wfm", ("WFM", "PLAN", "REPORT")),                       # planejamento / WFM / MIS
    ("gerentes", ("MGMT", "MANAGER", "DIRECTOR", "DIROPER", "OPERATIONS-", "GERENT")),
    ("supervisores", ("LEAD", "SUPERV", "COORD")),                 # team/floor leader
]


def categoria_staff(dept_code: str) -> str | None:
    """'TEAMLEADER-DIR' -> 'supervisores'; agente, indireto ou não-direto -> None."""
    d = str(dept_code or "").upper()
    if d == forecast.DEPT_AGENTE or "INDIR" in d or "DIR" not in d:
        return None
    for categoria, palavras in PALAVRAS_STAFF:
        if any(p in d for p in palavras):
            return categoria
    return "outros"                      # outro código direto de staff


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
    """
    PAs reservadas no CMAP (controle) neste mês:
    (agentes, {categoria de staff: quantidade}).
    """
    r = banco.db().execute(
        """SELECT a.dept_code, SUM(a.qtd) AS q FROM assentos a
           JOIN reservas r ON r.id = a.reserva_id
           WHERE r.project_id = ? AND r.location_id = ? AND r.status != 'Cancelado'
             AND a.mes = ? GROUP BY a.dept_code""",
        (project_id, location_id, mes.chave)).fetchall()
    agentes, staff = 0, defaultdict(int)
    for x in r:
        if x["dept_code"] == forecast.DEPT_AGENTE:
            agentes += x["q"]
        elif categoria_staff(x["dept_code"]):
            staff[categoria_staff(x["dept_code"])] += x["q"]
    return agentes, staff


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
    receptivo = subir._receptivo()            # receptivo digitado na tela Reserva

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
            res_ag, staff_cmap = _reservado(project_id, location_id, mes)
            # Projeto compartilhado com o receptivo: a parte dele não é do outbound
            rec = min(receptivo.get(chave, {}).get(mes.chave, 0), res_ag)
            res_ag -= rec
            res_st = sum(staff_cmap.values())                 # todo staff direto reservado
            d = detalhes.get(chave)
            digitado = {k: (d[k] if d else 0) for k, _ in CATEGORIAS_STAFF}
            # Linhas de staff: o que você digitou na tela; sem nada digitado, o que está
            # no CMAP (cada código na sua categoria).
            staff_do_cmap = not sum(digitado.values())
            staff_linhas = ({k: staff_cmap.get(k, 0) for k, _ in CATEGORIAS_STAFF} if staff_do_cmap
                            else digitado)
            staff_linhas["outros"] = staff_cmap.get("outros", 0) if staff_do_cmap else 0
            staff_ocup = sum(staff_linhas.values())
            staff_do_forecast = not staff_ocup and bool(calc[chave]["staff"].get(mes.chave, 0))
            if staff_do_forecast:                             # nada no CMAP nem digitado
                staff_ocup = calc[chave]["staff"][mes.chave]
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
                "receptivo": rec,
                "staff": staff_linhas, "staff_do_cmap": staff_do_cmap,
                "staff_digitado": digitado, "staff_do_forecast": staff_do_forecast,
                "st_ocup": staff_ocup, "st_disp": res_st, "st_pct": _pct(staff_ocup, res_st),
                "tot_ocup": ag_ocup + staff_ocup, "tot_disp": res_ag + res_st,
            })
        # Um quadro por CIDADE dentro de cada gestor (São Paulo, Curitiba, Ponta Grossa...)
        por_cidade = defaultdict(list)
        for c in colunas:
            por_cidade[banco.cidade(c["location_id"])].append(c)
        for cidade in por_cidade:
            blocos.append({"gerente": gerente, "cidade": cidade,
                           **_quadro(por_cidade[cidade])})
    # ordem: cidade (São Paulo, Curitiba, Ponta Grossa, Home Office) e depois gestor
    ordem = banco.ORDEM_CIDADES
    blocos.sort(key=lambda b: (ordem.index(b["cidade"]) if b["cidade"] in ordem else 99, b["gerente"]))
    return blocos


def _quadro(colunas):
    """Títulos das colunas e a coluna TOTAL de um quadro."""
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
             ("hc", "manha", "tarde", "home", "ag_ocup", "ag_disp", "receptivo", "st_ocup", "st_disp",
              "tot_ocup", "tot_disp")}
    total["staff"] = {k: sum(c["staff"][k] for c in colunas)
                      for k in [k for k, _ in CATEGORIAS_STAFF] + ["outros"]}
    for p in ("ag", "st", "tot"):
        total[f"{p}_pct"] = _pct(total[f"{p}_ocup"], total[f"{p}_disp"])
    return {"colunas": colunas, "total": total}


def gerentes():
    return [g["gerencia"] for g in banco.db().execute(
        """SELECT DISTINCT fr.gerencia FROM frentes fr
           WHERE fr.gerencia != '' AND (EXISTS (SELECT 1 FROM forecast f WHERE f.lob = fr.lob)
                 OR EXISTS (SELECT 1 FROM frentes_manuais m WHERE m.lob = fr.lob))
           ORDER BY fr.gerencia""")]
