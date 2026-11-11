"""
forecast.py — lê o FORECAST OFICIAL (aba BASE) e calcula o que vai para o CMAP.

Formato do arquivo: um bloco de ~30 linhas por frente (LOB WFM), uma linha por
indicador (coluna DADO) e uma coluna por mês. Usamos só estas linhas:

    6H20 ou 7H12                -> diz a carga da frente (meio período ou integral)
    MOP (ATIVO + AVISO PRÉVIO)  -> volumetria (pessoas)
    HOME MANHÃ / HOME TARDE     -> quantos do MOP trabalham de casa
    STAFF INCOMPANY / STAFF HOME

REGRAS (combinadas com a Anna em 11/11/2026):
  • No prédio:  PAs = (MOP − Home) ÷ fator
                fator = 2 para frentes 6H20 (duas pessoas dividem a PA)
                fator = 1 para integral (7H12)
  • Home:       vai numa reserva separada em WAH Brasil Direto WFH (_HO).
  • Staff:      entra como TEAMLEADER-DIR (só códigos diretos).
  • Arredondamento: SEMPRE PARA CIMA, depois de somar tudo do mesmo
    MAS + local (igual ao bloco "MSA / MESES" do controle antigo).
"""
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime

from openpyxl import load_workbook

import meses

LOCAL_HOME = "BR-WFH-DIRETO"
DEPT_AGENTE = "PRODUCAGENT-DIR"
DEPT_STAFF = "TEAMLEADER-DIR"

# Endereço do forecast (ENDEREÇO INTEGRATION) -> Location ID do CMAP.
# A busca é por "contém", sem acento e sem maiúsculas.
ENDERECOS = [
    ("jose loureiro 1", "BR-CUR-JOSEL-01"),
    ("jose loureiro 2", "BR-CUR-JOSEL-02"),
    ("jose loureiro 3", "BR-CUR-JOSEL-03"),
    ("marechal 2", "BR-CUR-MALDE-01"),
    ("marechal 3", "BR-CUR-MALDE-02"),
    ("muricy", "BR-CUR-MURIC"),
    ("ponta grossa", "BR-PON-RUASE"),
    ("tagipuru", "BR-SAO-TAGIP"),
    ("barueri", "BR-BAR-ARAGU"),
    ("araguaia", "BR-BAR-ARAGU"),
    ("ez tower", "BR-SAO-EZTOW"),
]

# Apelido curto de cada local, para montar o Resv. Desc. (ex.: CARREFOUR_MAL3).
APELIDOS = {
    "BR-SAO-TAGIP": "BF4", "BR-BAR-ARAGU": "BAR", "BR-CUR-JOSEL-01": "JL1",
    "BR-CUR-JOSEL-02": "JL2", "BR-CUR-JOSEL-03": "JL3", "BR-CUR-MALDE-01": "MAL2",
    "BR-CUR-MALDE-02": "MAL3", "BR-PON-RUASE": "PG", LOCAL_HOME: "HO",
}

# Linhas (DADO) que interessam, já normalizadas.
DADO_MOP = "mop (ativo + aviso previo)"
DADOS_HOME = {"home manha", "home tarde"}
DADO_STAFF_IC = "staff incompany"
DADO_STAFF_HO = "staff home"
CARGAS = {"6h20": 2, "7h12": 1}


class ErroForecast(Exception):
    """Problema no arquivo (mensagem mostrada para o usuário)."""


def normalizar(texto) -> str:
    """'Curitiba José  Loureiro' -> 'curitiba jose loureiro' (sem acento, minúsculo)."""
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().lower()


def local_do_endereco(endereco, andar) -> str | None:
    if "home" in normalizar(andar) or "home" in normalizar(endereco):
        return LOCAL_HOME
    end = normalizar(endereco)
    for trecho, location_id in ENDERECOS:
        if trecho in end:
            return location_id
    return None


def _numero(valor) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):     # '#DIV/0!', '-', texto
        return 0.0


# ================================================================ LER

def ler(arquivo):
    """
    Lê a aba BASE e devolve (frentes, avisos).
    Cada frente: lob, act_id, conta, endereco, andar, location_id, carga, fator,
                 valores = {mes: {"mop", "home", "staff_ic", "staff_ho"}}
    """
    try:
        livro = load_workbook(arquivo, read_only=True, data_only=True)
    except Exception as erro:
        raise ErroForecast("Não consegui abrir o arquivo. Ele é um .xlsx válido?") from erro
    try:
        if "BASE" not in livro.sheetnames:
            raise ErroForecast("Não encontrei a aba BASE do forecast.")
        linhas = livro["BASE"].iter_rows(values_only=True)
        cab = [normalizar(c) if not isinstance(c, datetime) else c for c in next(linhas)]
        col = {nome: cab.index(nome) for nome in
               ("lob wfm", "dado", "endereco integration", "andar", "conta", "act id")
               if nome in cab}
        if {"lob wfm", "dado", "endereco integration"} - col.keys():
            raise ErroForecast("A aba BASE não tem as colunas LOB WFM, DADO e ENDEREÇO INTEGRATION.")
        # colunas de mês = cabeçalhos que são datas (as semanas W-45... são ignoradas)
        col_meses = {i: meses.de_valor(c).chave for i, c in enumerate(cab) if isinstance(c, datetime)}

        frentes: dict[tuple, dict] = {}
        for r in linhas:
            lob = str(r[col["lob wfm"]] or "").strip()
            dado = normalizar(r[col["dado"]])
            if not lob or lob == "-" or not dado or dado == "-":
                continue
            endereco = str(r[col["endereco integration"]] or "").strip()
            andar = str(r[col["andar"]] or "").strip() if "andar" in col else ""
            f = frentes.setdefault((lob, endereco, andar), {
                "lob": lob, "endereco": endereco, "andar": andar,
                "act_id": str(r[col["act id"]] or "").strip() if "act id" in col else "",
                "conta": str(r[col["conta"]] or "").strip() if "conta" in col else "",
                "location_id": local_do_endereco(endereco, andar),
                "carga": None, "fator_arquivo": None,
                "valores": defaultdict(lambda: {"mop": 0.0, "home": 0.0,
                                                "staff_ic": 0.0, "staff_ho": 0.0}),
            })
            if dado in CARGAS:
                f["carga"] = dado.upper()
            elif dado == "fator pa":
                f["fator_arquivo"] = next((_numero(r[i]) for i in col_meses if r[i] not in (None, "")), None)
            campo = ("mop" if dado == DADO_MOP else "home" if dado in DADOS_HOME else
                     "staff_ic" if dado == DADO_STAFF_IC else "staff_ho" if dado == DADO_STAFF_HO else None)
            if campo:
                for i, mes in col_meses.items():
                    f["valores"][mes][campo] += _numero(r[i] if i < len(r) else 0)
    finally:
        livro.close()

    if not frentes:
        raise ErroForecast("Nenhuma frente encontrada na aba BASE.")

    avisos = []
    for f in frentes.values():
        f["fator"] = CARGAS.get((f["carga"] or "").lower(), 1)
        if not f["carga"]:
            avisos.append(f"{f['lob']}: sem linha 6H20/7H12 — considerei integral (fator 1).")
        if f["fator_arquivo"] not in (None, f["fator"]):
            avisos.append(f"{f['lob']}: FATOR PA no arquivo é {f['fator_arquivo']:g}, "
                          f"mas pela regra ({f['carga']}) usei {f['fator']}.")
        if not f["location_id"]:
            avisos.append(f"{f['lob']}: endereço “{f['endereco']}” não reconhecido.")
    return list(frentes.values()), avisos


# ================================================================ CALCULAR

def calcular(frentes, de_para: dict, janela: list[meses.Mes], acompanho) -> dict:
    """
    Junta as frentes por MAS (Project ID) + local e aplica as regras.

    de_para: {lob: {"project_id", "project_name", "cliente"}}
    acompanho(location_id) -> bool
    Devolve {(project_id, location_id): {"info", "agentes": {mes: n}, "staff": {mes: n},
                                         "lobs": set(), "detalhe": [...]}}
    """
    chaves = [m.chave for m in janela]
    brutos = defaultdict(lambda: {"agentes": defaultdict(float), "staff": defaultdict(float),
                                  "lobs": set(), "info": None})
    for f in frentes:
        dp = de_para.get(f["lob"])
        if not dp or not dp.get("project_id") or not f["location_id"]:
            continue
        for mes in chaves:
            v = f["valores"].get(mes)
            if not v:
                continue
            home = min(v["home"], v["mop"])
            if f["location_id"] == LOCAL_HOME:          # frente 100% home office
                destinos = [(LOCAL_HOME, v["mop"], v["staff_ic"] + v["staff_ho"])]
            else:
                destinos = [(f["location_id"], (v["mop"] - home) / f["fator"], v["staff_ic"]),
                            (LOCAL_HOME, home, v["staff_ho"])]
            for location_id, agentes, staff in destinos:
                if not acompanho(location_id) or (agentes <= 0 and staff <= 0):
                    continue
                b = brutos[(dp["project_id"], location_id)]
                b["agentes"][mes] += agentes
                b["staff"][mes] += staff
                b["lobs"].add(f["lob"])
                b["info"] = b["info"] or {**dp, "conta": f["conta"]}

    # arredonda SEMPRE para cima, já com tudo somado
    for b in brutos.values():
        b["agentes"] = {m: math.ceil(round(q, 6)) for m, q in b["agentes"].items()}
        b["staff"] = {m: math.ceil(round(q, 6)) for m, q in b["staff"].items()}
    return dict(brutos)


def resv_desc(info: dict, location_id: str) -> str:
    """Nome sugerido para a reserva nova, no padrão do CMAP: CARREFOUR_MAL3."""
    base = re.sub(r"[^A-Z0-9]+", "_", normalizar(info.get("cliente") or info.get("conta")).upper()).strip("_")
    return f"{base or info['project_id']}_{APELIDOS.get(location_id, location_id[-5:])}"


# ================================================================ DE-PARA DO CONTROLE ANTIGO

def ler_de_para(arquivo) -> dict:
    """
    Lê LOB WFM -> MAS de qualquer aba que tenha as colunas 'LOB WFM' e 'MAS'
    (ex.: a BASE do controle antigo "CMAP - Desbloquear") e também 'CONTA'.
    """
    try:
        livro = load_workbook(arquivo, read_only=True, data_only=True)
    except Exception as erro:
        raise ErroForecast("Não consegui abrir o arquivo. Ele é um .xlsx válido?") from erro
    achados = {}
    try:
        for aba in livro.worksheets:
            linhas = aba.iter_rows(values_only=True)
            cab = [normalizar(c) for c in next(linhas, [])]
            if "lob wfm" not in cab or "mas" not in cab:
                continue
            i_lob, i_mas = cab.index("lob wfm"), cab.index("mas")
            i_conta = cab.index("conta") if "conta" in cab else None
            for r in linhas:
                lob = str(r[i_lob] or "").strip()
                mas = str(r[i_mas] or "").strip().upper()
                if lob and lob != "-" and re.match(r"^[A-Z0-9][A-Z0-9_\-]{1,39}$", mas):
                    achados.setdefault(lob, {"project_id": mas,
                                             "cliente": str(r[i_conta] or "").strip()
                                             if i_conta is not None else ""})
    finally:
        livro.close()
    if not achados:
        raise ErroForecast("Não encontrei as colunas LOB WFM e MAS em nenhuma aba.")
    return achados
