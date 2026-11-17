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
import math
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
    "BR-SAO-EZTOW": "EZ Tower", "BR-CUR-MURIC": "Muricy",
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
    ("qualidade", ("QUAL", "TRAIN", "TRAN", "EVALU")),            # qualidade, treinamento, monitoria
    ("plan_wfm", ("WFM", "PLAN", "REPORT")),                       # planejamento / WFM / MIS
    ("gerentes", ("MGMT", "MANAGER", "DIRECTOR", "DIROPER", "OPERATIONS-", "GERENT")),
    ("supervisores", ("LEAD", "SUPERV", "COORD")),                 # team/floor leader
]


def categoria_staff(dept_code: str) -> str | None:
    """'TEAMLEADER-DIR' -> 'supervisores'; agente, indireto ou não-direto -> None."""
    d = str(dept_code or "").upper()
    if d == forecast.DEPT_AGENTE or "INDIR" in d or "DIR" not in d:
        return None
    if "AUDIT" in d:                      # AGENTAUDITO-DIR (auditor): não é usado na operação
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
    Um quadro por gestor e cidade: [{"gerente", "cidade", "colunas": [...], "total": {...}}].

    1) Monta as colunas (conta + prédio) de cada gestor com o que o forecast pede.
       Home office entra na cidade do ENDEREÇO da frente (ex.: TIM - PG fica em Ponta Grossa).
    2) Junta com o que está reservado no CMAP. Quando o mesmo MAS + prédio é de mais de um
       gestor/cidade (ex.: Claro cobrança em M3), o reservado é DIVIDIDO na proporção das
       PAs ocupadas de cada coluna — senão ele apareceria inteiro em todos.
    """
    colunas = _colunas_do_forecast(mes)
    _juntar_cmap(colunas, mes)

    blocos = defaultdict(list)
    for c in colunas:
        blocos[(c["gerente"], c["cidade"])].append(c)
    ordem = banco.ORDEM_CIDADES
    lista = [{"gerente": g, "cidade": cid, **_quadro(cols)} for (g, cid), cols in blocos.items()]
    lista.sort(key=lambda b: (ordem.index(b["cidade"]) if b["cidade"] in ordem else 99, b["gerente"]))
    return lista


def _cidade_do_endereco(frente) -> str:
    """Cidade pelo endereço do forecast (o andar "HOME OFFICE" não muda a cidade)."""
    local = forecast.local_do_endereco(frente.get("endereco", ""), "")
    if local and local != forecast.LOCAL_HOME:
        return banco.cidade(local)
    if frente["location_id"] and frente["location_id"] != forecast.LOCAL_HOME:
        return banco.cidade(frente["location_id"])
    return "Home Office"


def _colunas_do_forecast(mes):
    """Colunas (gestor, cidade, MAS, local) com HCs e PAs ocupadas pelo forecast."""
    de_para = subir.de_para()
    ativos = {l["location_id"] for l in banco.locais(somente_ativos=True)}
    por_gerente = defaultdict(list)
    for f in subir.frentes_salvas():
        por_gerente[f.get("gerencia") or "(sem gestor)"].append(f)

    colunas = []
    for gerente, lista in por_gerente.items():
        # PAs no prédio pela regra, calculadas só com as frentes deste gestor
        calc = forecast.calcular(lista, de_para, [mes], lambda l: l in ativos)
        brutos = defaultdict(lambda: {"hc": 0.0, "manha": 0.0, "tarde": 0.0, "home": 0.0,
                                      "pas_home": 0.0, "staff_home": 0.0,
                                      "andares": set(), "contas": set(), "lobs": set()})
        for f in lista:
            dp = de_para.get(f["lob"])
            v = f["valores"].get(mes.chave)
            if not dp or not dp.get("project_id") or not v or not f["location_id"]:
                continue
            home = min(v["home"], v["mop"])
            cidade = _cidade_do_endereco(f)
            if f["location_id"] == forecast.LOCAL_HOME:          # frente 100% home office
                destinos = [(forecast.LOCAL_HOME, v["mop"], 0, 0, v["mop"],
                             v["staff_ic"] + v["staff_ho"])]
            else:
                meio = f["fator"] == 2                  # manhã/tarde só nas frentes 6H20
                destinos = [(f["location_id"], v["mop"], v.get("ic_manha", 0) if meio else 0,
                             v.get("ic_tarde", 0) if meio else 0, home, 0)]
                if home or v["staff_ho"]:
                    destinos.append((forecast.LOCAL_HOME, home, 0, 0, home, v["staff_ho"]))
            for loc, hc, manha, tarde, ho, staff_ho in destinos:
                if loc not in ativos:
                    continue
                b = brutos[(dp["project_id"], loc, cidade if loc == forecast.LOCAL_HOME
                            else banco.cidade(loc))]
                b["hc"] += hc
                b["manha"] += manha
                b["tarde"] += tarde
                b["home"] += ho
                if loc == forecast.LOCAL_HOME:
                    b["pas_home"] += ho               # em casa: 1 pessoa = 1 posição no CMAP
                    b["staff_home"] += staff_ho
                b["andares"].add(andar_curto(f["andar"]) if loc == f["location_id"] else "HO")
                b["contas"].add((f["conta"] or dp.get("cliente") or "").upper())
                b["lobs"].add(f["lob"])

        for (project_id, location_id, cidade), b in brutos.items():
            if location_id == forecast.LOCAL_HOME:
                ag_ocup = math.ceil(round(b["pas_home"], 6))
                staff_fc = math.ceil(round(b["staff_home"], 6))
            else:
                c = calc.get((project_id, location_id), {"agentes": {}, "staff": {}})
                ag_ocup = c["agentes"].get(mes.chave, 0)
                staff_fc = c["staff"].get(mes.chave, 0)
            andares = sorted(a for a in b["andares"] if a != "HO") or ["HO"]
            colunas.append({
                "gerente": gerente, "cidade": cidade,
                "project_id": project_id, "location_id": location_id,
                "conta": " / ".join(sorted(b["contas"])),
                "site": (f"{CURTOS.get(location_id, location_id)} - {', '.join(andares)}"
                         if location_id != forecast.LOCAL_HOME else "Home Office"),
                "lobs": sorted(b["lobs"]),
                "hc": round(b["hc"]), "manha": round(b["manha"]), "tarde": round(b["tarde"]),
                "home": round(b["home"]), "ag_ocup": ag_ocup, "staff_fc": staff_fc,
            })
    return colunas


def _dividir(total: int, pesos: list) -> list[int]:
    """Divide um inteiro na proporção dos pesos (maiores restos recebem a sobra)."""
    if len(pesos) == 1:
        return [total]
    soma = sum(pesos)
    pesos = pesos if soma else [1] * len(pesos)
    soma = sum(pesos)
    exatos = [total * p / soma for p in pesos]
    partes = [math.floor(x) for x in exatos]
    for i in sorted(range(len(pesos)), key=lambda i: exatos[i] - partes[i], reverse=True)[:total - sum(partes)]:
        partes[i] += 1
    return partes


def _juntar_cmap(colunas, mes):
    """Coloca o reservado no CMAP (dividido quando compartilhado), staff e percentuais."""
    detalhes = _detalhes()
    receptivo = subir._receptivo()            # receptivo digitado na tela Reserva
    grupos = defaultdict(list)
    for c in colunas:
        grupos[(c["project_id"], c["location_id"])].append(c)

    categorias = [k for k, _ in CATEGORIAS_STAFF]
    for chave, cols in grupos.items():
        res_ag, staff_cmap = _reservado(*chave, mes)
        # Projeto compartilhado com o receptivo: a parte dele não é do outbound
        rec = min(receptivo.get(chave, {}).get(mes.chave, 0), res_ag)
        d = detalhes.get(chave)
        digitado = {k: (d[k] if d else 0) for k in categorias}
        staff_do_cmap = not sum(digitado.values())
        # Linhas de staff: o que você digitou; sem nada digitado, o que está no CMAP.
        fonte = dict(staff_cmap) if staff_do_cmap else {**digitado, "outros": 0}
        pesos = [c["ag_ocup"] for c in cols]
        partes_ag = _dividir(res_ag - rec, pesos)
        partes_rec = _dividir(rec, pesos)
        partes_st = {k: _dividir(fonte.get(k, 0), pesos) for k in categorias + ["outros"]}
        partes_disp_st = _dividir(sum(staff_cmap.values()), pesos)
        for i, c in enumerate(cols):
            staff = {k: partes_st[k][i] for k in categorias + ["outros"]}
            st_ocup = sum(staff.values())
            do_forecast = not st_ocup and bool(c["staff_fc"])
            if do_forecast:                       # nada no CMAP nem digitado
                st_ocup = c["staff_fc"]
            ag_disp, st_disp = partes_ag[i], partes_disp_st[i]
            c.update({
                "particularidades": d["particularidades"] if d else "",
                "dividido": len(cols) > 1,
                "ag_disp": ag_disp, "ag_pct": _pct(c["ag_ocup"], ag_disp), "receptivo": partes_rec[i],
                "staff": staff, "staff_do_cmap": staff_do_cmap, "staff_digitado": digitado,
                "staff_do_forecast": do_forecast,
                "st_ocup": st_ocup, "st_disp": st_disp, "st_pct": _pct(st_ocup, st_disp),
                "tot_ocup": c["ag_ocup"] + st_ocup, "tot_disp": ag_disp + st_disp,
            })


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


def sem_mas_por_gestor():
    """Frentes do forecast sem MAS (ficam fora dos quadros), contadas por gestor."""
    return banco.db().execute(
        """SELECT CASE WHEN fr.gerencia = '' THEN '(sem gestor)' ELSE fr.gerencia END AS gerente,
                  COUNT(DISTINCT fr.lob) AS frentes, group_concat(DISTINCT fr.lob) AS lobs
           FROM frentes fr JOIN forecast f ON f.lob = fr.lob
           WHERE fr.project_id = '' GROUP BY 1 ORDER BY 1""").fetchall()
