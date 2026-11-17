"""
forecast.py — lê o FORECAST OFICIAL (aba BASE) e calcula o que vai para o CMAP.

Formato do arquivo: um bloco de ~30 linhas por frente (LOB WFM), uma linha por
indicador (coluna DADO) e uma coluna por mês. Usamos só estas linhas:

    6H20 ou 7H12                -> diz a carga da frente (meio período ou integral)
    MOP (ATIVO + AVISO PRÉVIO)  -> volumetria (pessoas)
    HOME MANHÃ / HOME TARDE     -> quantos do MOP trabalham de casa
    STAFF INCOMPANY / STAFF HOME

REGRAS (combinadas com a Anna em 11/11/2026; maior turno em 17/11/2026):
  • No prédio:  presencial = MOP − Home
                integral (7H12): PAs = presencial
                6H20: manhã e tarde usam a MESMA PA, então conta o MAIOR TURNO.
                      O presencial é dividido entre manhã e tarde na proporção das
                      linhas INCOMPANY MANHÃ / TARDE do forecast:
                      PAs = presencial × maior turno ÷ (manhã + tarde)
                      (sem manhã/tarde no arquivo: presencial ÷ 2)
  • Home:       vai numa reserva separada em WAH Brasil Direto WFH (_HO).
  • Staff:      entra como TEAMLEADER-DIR (só códigos diretos).
  • Arredondamento: SEMPRE PARA CIMA, depois de somar tudo do mesmo
    MAS + local (igual ao bloco "MSA / MESES" do controle antigo).
"""
import math
import re
import unicodedata
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

# Avisos técnicos do openpyxl ("Data Validation extension is not supported"...) não são
# erros: o Excel do forecast usa recursos que a leitura simplesmente ignora.
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

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
DADOS_TURNO = {"incompany manha": "ic_manha", "incompany tarde": "ic_tarde"}
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

OBRIGATORIAS = {"lob wfm", "dado", "endereco integration"}
LINHAS_CABECALHO = 60


def _achar_cabecalho(livro):
    """
    Procura a linha de cabeçalho (LOB WFM, DADO, ENDEREÇO INTEGRATION) em qualquer
    aba, nas 60 primeiras linhas — começando pela aba BASE. Assim o arquivo pode
    mudar de nome, de aba ou ganhar linhas de título em cima sem quebrar a leitura.
    Devolve (iterador das linhas seguintes, cabeçalho normalizado).
    """
    abas = sorted(livro.worksheets, key=lambda a: a.title.strip().upper() != "BASE")
    for aba in abas:
        linhas = aba.iter_rows(values_only=True)
        for _n, linha in zip(range(LINHAS_CABECALHO), linhas):
            cab = [normalizar(c) if not isinstance(c, datetime) else c for c in linha]
            if OBRIGATORIAS <= set(c for c in cab if isinstance(c, str)):
                return linhas, cab
    raise ErroForecast("Não encontrei o forecast: nenhuma aba tem as colunas LOB WFM, DADO e "
                       "ENDEREÇO INTEGRATION nas primeiras 60 linhas (normalmente fica na aba BASE).")

def ler(arquivo):
    """
    Lê a aba BASE e devolve (frentes, avisos).
    Cada frente: lob, act_id, conta, endereco, andar, location_id, carga, fator,
                 valores = {mes: {"mop", "home", "staff_ic", "staff_ho"}}
    """
    try:
        livro = load_workbook(arquivo, read_only=True, data_only=True)
    except PermissionError as erro:
        raise ErroForecast("O forecast está bloqueado — aberto no Excel ou o OneDrive está "
                           "sincronizando. Espere o ícone ficar verde (✓) e atualize a página.") from erro
    except Exception as erro:
        raise ErroForecast("Não consegui abrir o arquivo. Ele é um .xlsx válido?") from erro
    try:
        linhas, cab = _achar_cabecalho(livro)
        col = {nome: cab.index(nome) for nome in
               ("lob wfm", "dado", "endereco integration", "andar", "conta", "act id", "gerencia")
               if nome in cab}
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
                "gerencia": str(r[col["gerencia"]] or "").strip() if "gerencia" in col else "",
                "location_id": local_do_endereco(endereco, andar),
                "carga": None, "fator_arquivo": None,
                "valores": defaultdict(lambda: {"mop": 0.0, "home": 0.0, "staff_ic": 0.0,
                                                "staff_ho": 0.0, "ic_manha": 0.0, "ic_tarde": 0.0}),
            })
            if dado in CARGAS:
                f["carga"] = dado.upper()
            elif dado == "fator pa":
                f["fator_arquivo"] = next((_numero(r[i]) for i in col_meses if r[i] not in (None, "")), None)
            campo = ("mop" if dado == DADO_MOP else "home" if dado in DADOS_HOME else
                     "staff_ic" if dado == DADO_STAFF_IC else "staff_ho" if dado == DADO_STAFF_HO else
                    DADOS_TURNO.get(dado))
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
                          f"mas é {f['carga']}: calculei "
                          + ("pelo maior turno (manhã/tarde)." if f["fator"] == 2 else "como integral (1 PA por pessoa)."))
        if not f["location_id"]:
            avisos.append(f"{f['lob']}: endereço “{f['endereco']}” não reconhecido.")
    return list(frentes.values()), avisos


# ================================================================ LIGAÇÃO COM O ARQUIVO (caminhos.txt)

def ler_caminhos(arquivo: Path) -> dict:
    """
    Lê o caminhos.txt (mesmo formato do gerador das atas):
        forecast = C:\\Users\\voce\\OneDrive\\Forecast\\FORECAST OFICIAL.xlsx
    Pode ser o arquivo ou a pasta. Linhas com # são ignoradas.
    """
    caminhos = {}
    if not arquivo.exists():
        return caminhos
    for linha in arquivo.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, valor = (x.strip().strip('"').strip() for x in linha.split("=", 1))
        caminhos[normalizar(nome).replace(" ", "")] = valor
    return caminhos


def motivo_para_nao_ler(arquivo: Path) -> str | None:
    """
    Abre só o cabeçalho (rápido). Devolve None se é um forecast que dá para ler,
    ou o motivo em português de não conseguir.
    """
    try:
        livro = load_workbook(arquivo, read_only=True, data_only=True)
    except PermissionError:
        return ("está bloqueado — aberto no Excel ou o OneDrive está sincronizando. "
                "Espere o ícone ficar verde (✓) ou feche o arquivo")
    except OSError:
        return ("o OneDrive não deixou ler — talvez só exista na nuvem. Botão direito no arquivo > "
                "“Sempre manter neste dispositivo”")
    except Exception:
        return "não é um Excel (.xlsx) que eu consiga abrir"
    try:
        _achar_cabecalho(livro)
        return None
    except ErroForecast:
        return "não tem as colunas do forecast (LOB WFM, DADO e ENDEREÇO INTEGRATION)"
    finally:
        livro.close()


def diagnosticar(caminho: str):
    """
    Procura o forecast no caminho (arquivo ou pasta) e explica o que achou.
    Devolve (arquivo ou None, lista de motivos para mostrar ao usuário).
    """
    alvo = Path(str(caminho).strip().strip('"')).expanduser()
    if alvo.is_file():
        motivo = motivo_para_nao_ler(alvo)
        return (None, [f"{alvo.name}: {motivo}."]) if motivo else (alvo, [])
    if alvo.is_dir():
        # primeiro os que têm "forecast" no nome; depois os mais recentes
        candidatos = sorted((p for p in alvo.glob("*.xlsx") if not p.name.startswith("~$")),
                            key=lambda p: ("forecast" not in normalizar(p.name), -p.stat().st_mtime))
        motivos = []
        for arq in candidatos:
            motivo = motivo_para_nao_ler(arq)
            if not motivo:
                return arq, []
            motivos.append(f"{arq.name}: {motivo}.")
        return None, motivos or ["a pasta não tem nenhum arquivo .xlsx."]
    dica = (" Se aparece “...” no meio, pode ser abreviação do Windows: use Copiar como caminho."
            if "..." in str(alvo) and not alvo.parent.exists() else "")
    return None, [f"esse caminho não existe neste computador.{dica}"]


def achar_arquivo(caminho: str) -> Path | None:
    """O arquivo informado, ou o forecast salvo por último dentro da pasta informada."""
    return diagnosticar(caminho)[0]


# ================================================================ CALCULAR

def pas_no_predio(frente: dict, v: dict) -> float:
    """
    PAs que a frente ocupa no prédio num mês (antes de arredondar).
    Exemplo 6H20: MOP 60, home 0, manhã 45, tarde 15 -> 60 × 45 ÷ 60 = 45 PAs.
    """
    presencial = max(v["mop"] - min(v["home"], v["mop"]), 0)
    if frente["fator"] != 2:                          # integral: 1 pessoa = 1 PA
        return presencial
    manha, tarde = v.get("ic_manha", 0), v.get("ic_tarde", 0)
    if manha + tarde <= 0:                            # sem divisão no arquivo
        return presencial / 2
    return presencial * max(manha, tarde) / (manha + tarde)


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
                destinos = [(f["location_id"], pas_no_predio(f, v), v["staff_ic"]),
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
