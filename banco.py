"""
banco.py — o banco de dados do controle.

Usamos SQLite: é um arquivo único (instance/cmap.db) que fica só no seu PC.
Não precisa instalar nada, e o arquivo NUNCA vai para o GitHub (.gitignore).

Tabelas (mesmos nomes de campos do CMAP):
  locais    -> "Disponibilidade de locais" (de-para de Location ID / Site ID)
  reservas  -> "Ver reserva" (Resv. Desc., ID do projeto, status...)
  assentos  -> aba "Assentos" de cada reserva (Dept Code x mês)
  historico -> quem mudou o quê e quando (bom para auditoria)
"""
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import datetime

from flask import current_app, g

import meses

# Status possíveis de uma reserva (os dois primeiros aparecem no CMAP).
STATUS = ["Confirmado", "Fila mensal", "Rascunho", "Cancelado"]

# Quais status "ocupam" assentos na conta do painel.
STATUS_QUE_OCUPAM = ["Confirmado", "Fila mensal"]

# Os locais que EU acompanho. Só eles entram no painel, nas reservas e na
# importação. Os demais (Fortaleza, EZ Tower...) são ignorados.
# Para acompanhar outro local, marque "Acompanho" na tela Locais.
MEUS_LOCAIS = {
    "BR-SAO-TAGIP",     # São Paulo — Barra Funda BF4
    "BR-BAR-ARAGU",     # São Paulo — Barueri
    "BR-CUR-JOSEL-01",  # Curitiba — JL1
    "BR-CUR-JOSEL-02",  # Curitiba — JL2
    "BR-CUR-JOSEL-03",  # Curitiba — JL3
    "BR-CUR-MALDE-01",  # Curitiba — Marechal 2
    "BR-CUR-MALDE-02",  # Curitiba — Marechal 3
    "BR-PON-RUASE",     # Ponta Grossa
    "BR-WFH-DIRETO",    # WAH Brasil Direto WFH (reservas _HO do home office)
}

# Locais do CMAP Brasil (tela "Disponibilidade de locais"): Location ID, Site ID, descrição.
# Entram sozinhos na primeira vez que o controle abre; a capacidade você digita em Locais.
LOCAIS_CMAP = [
    ("BR-BAR-ARAGU", "BAA", "Barueri Araguaia"),
    ("BR-CEA-LEDOS", "", "Fortaleza Gonçalves Ledo"),
    ("BR-CUR-BARAO", "", "Curitiba Barão"),
    ("BR-CUR-JOSEL-01", "CJ1", "Curitiba José Loureiro 1"),
    ("BR-CUR-JOSEL-02", "CJ2", "Curitiba José Loureiro 2"),
    ("BR-CUR-JOSEL-03", "", "Curitiba José Loureiro 3"),
    ("BR-CUR-MALDE-01", "CM2", "Curitiba Marechal 2"),
    ("BR-CUR-MALDE-02", "", "Curitiba Marechal 3"),
    ("BR-CUR-MALDE-03", "", "Curitiba Tibagi"),
    ("BR-CUR-MURIC", "", "Curitiba Muricy"),
    ("BR-PON-RUASE", "BPG", "Ponta Grossa"),
    ("BR-SAO-EZTOW", "", "Torre EZ de São Paulo"),
    ("BR-SÃO-FRANÇA", "", "São Paulo Água Branca"),
    ("BR-SAO-TAGIP", "", "São Paulo Barra Funda BF4 Tagipuru"),
    ("BR-WFH-DIRETO", "BWD", "WAH Brasil Direto WFH"),
    ("BR-WFH-INDIR", "", "Trabalho Remoto - Indireto"),
]

# ---------------------------------------------------------------- minhas carteiras
# As carteiras que EU cuido = as CONTAs do forecast + as incluídas à mão em Frentes.
# (Nenhum nome de cliente fica no código.) O resto do CMAP (outras carteiras do prédio)
# é ignorado no Painel, na Reserva, em Gestores e em Ver reserva.

def _limpo(texto) -> str:
    """'P_CLARO COBRANCA_CWB' -> 'CLAROCOBRANCACWB' (sem acento, espaço e o P_ do começo)."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper().strip()
    t = re.sub(r"^P_", "", t)
    return re.sub(r"[^A-Z0-9]", "", t)


def minhas_carteiras() -> list[str]:
    """Contas do forecast e das carteiras manuais (guardado por requisição)."""
    if "carteiras" not in g:
        g.carteiras = [r["conta"] for r in db().execute(
            """SELECT DISTINCT conta FROM frentes WHERE conta != '' AND (
                 EXISTS (SELECT 1 FROM forecast f WHERE f.lob = frentes.lob)
                 OR EXISTS (SELECT 1 FROM frentes_manuais m WHERE m.lob = frentes.lob))
               ORDER BY conta""")]
    return g.carteiras


def carteira_de(cliente, projeto="", carteiras=None) -> str | None:
    """
    Qual das minhas carteiras é esta reserva do CMAP? None = não é minha.
    Compara o começo dos nomes, sem espaço/acento:
      cliente 'NATURA_CO' -> NATURA · 'NIOTELECOM' -> NIO · 'VIAVAREJO' -> VIA VAREJO
      cliente 'CLARO' combina com CLARO COBRANÇA e CLARO EMPRESAS: desempata pelo projeto
      ('P_CD - CLARO EMPRESAS' -> CLARO EMPRESAS); sem pista, fica a primeira em ordem alfabética.
    Sem forecast ainda (lista vazia): tudo conta como meu.
    """
    carteiras = minhas_carteiras() if carteiras is None else carteiras
    if not carteiras:
        return str(cliente or projeto or "(sem cliente)")
    cli, proj = _limpo(cliente), _limpo(projeto)
    candidatas = []
    for nome in carteiras:
        c = _limpo(nome)
        if not c:
            continue
        if (cli and (cli.startswith(c) or (len(cli) >= 3 and c.startswith(cli)))) or \
                (proj and proj.startswith(c)):
            candidatas.append(nome)
    if len(candidatas) > 1:
        # desempate: a carteira cujo nome inteiro aparece no projeto
        no_projeto = [n for n in candidatas if _limpo(n) in proj]
        if no_projeto:
            return no_projeto[0]
        # sem pista (ex.: P_CLARO RCV_CWB): fica a parte comum dos nomes ("CLARO")
        comum = os.path.commonprefix([n.split() for n in sorted(candidatas)])
        return " ".join(comum) if comum else sorted(candidatas)[0]
    return candidatas[0] if candidatas else None


def eh_receptivo(projeto) -> bool:
    """Projeto só de receptivo (inbound), pelo nome: P_CLARO RCV_CWB, ...RECEPTIVO..."""
    nome = _limpo(projeto)
    return "RCV" in nome or "RECEPT" in nome


# Alguns relatórios do CMAP usam outro código para o mesmo local.
# Código do relatório -> código da tela "Disponibilidade de locais".
CODIGOS_IGUAIS = {
    "BR-WFH-DRECT": "BR-WFH-DIRETO",
    "BR-SAO-FRANC": "BR-SÃO-FRANÇA",
}


def codigo_local(location_id: str) -> str:
    """Devolve o código usado no controle (troca os códigos alternativos)."""
    codigo = str(location_id or "").strip()
    return CODIGOS_IGUAIS.get(codigo.upper(), codigo)


# Cidade de cada local, pelo pedaço do meio do código (BR-CUR-... = Curitiba).
# A ordem aqui é a ordem dos grupos no painel.
CIDADES = {"SAO": "São Paulo", "BAR": "São Paulo", "CUR": "Curitiba", "PON": "Ponta Grossa",
           "WFH": "Home Office"}
ORDEM_CIDADES = ["São Paulo", "Curitiba", "Ponta Grossa", "Home Office"]


def cidade(location_id: str) -> str:
    partes = location_id.split("-")
    return CIDADES.get(partes[1] if len(partes) > 1 else "", "Outros")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS locais (
    location_id  TEXT PRIMARY KEY,          -- ex.: BR-PON-RUASE
    site_id      TEXT NOT NULL DEFAULT '',  -- ex.: BPG
    descricao    TEXT NOT NULL,             -- ex.: Ponta Grossa
    capacidade   INTEGER NOT NULL DEFAULT 0, -- total de posições (Prod + TL)
    ativo        INTEGER NOT NULL DEFAULT 1  -- 1 = local que eu acompanho
);

CREATE TABLE IF NOT EXISTS reservas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    resv_desc     TEXT NOT NULL,            -- ex.: CARREFOUR_PG
    project_id    TEXT NOT NULL,            -- ex.: WHBRASIL006
    project_name  TEXT NOT NULL,            -- ex.: P_CARREFOUR ATACADAO COBRANCA_CWB
    cliente       TEXT NOT NULL DEFAULT '', -- ex.: CARREFOUR
    location_id   TEXT NOT NULL REFERENCES locais(location_id),
    status        TEXT NOT NULL,
    criado_em     TEXT NOT NULL,            -- AAAA-MM-DD
    criado_por    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assentos (
    reserva_id  INTEGER NOT NULL REFERENCES reservas(id) ON DELETE CASCADE,
    dept_code   TEXT NOT NULL,              -- ex.: PRODUCAGENT-DIR
    dept_name   TEXT NOT NULL DEFAULT '',   -- ex.: COGS (SITE) Production Agent Direct
    shift       TEXT NOT NULL DEFAULT 'DED',
    mes         TEXT NOT NULL,              -- AAAA-MM
    qtd         INTEGER NOT NULL CHECK (qtd >= 0),
    PRIMARY KEY (reserva_id, dept_code, shift, mes)
);

-- De-para das frentes do forecast: LOB WFM -> MAS (Project ID do CMAP).
CREATE TABLE IF NOT EXISTS frentes (
    lob           TEXT PRIMARY KEY,         -- LOB WFM, como vem no forecast
    act_id        TEXT NOT NULL DEFAULT '',
    conta         TEXT NOT NULL DEFAULT '',
    project_id    TEXT NOT NULL DEFAULT '', -- MAS, ex.: WHBRASIL006
    project_name  TEXT NOT NULL DEFAULT '',
    cliente       TEXT NOT NULL DEFAULT '',
    gerencia      TEXT NOT NULL DEFAULT '', -- gestor (coluna GERENCIA do forecast)
    mas_sugerido  INTEGER NOT NULL DEFAULT 0 -- 1 = MAS preenchido sozinho pela conta (conferir)
);

-- Receptivo (inbound), digitado mês a mês na tela Reserva. Fica na mesma reserva do
-- CMAP que o outbound quando o projeto é compartilhado (ex.: Via Varejo, Carrefour).
CREATE TABLE IF NOT EXISTS receptivo (
    project_id   TEXT NOT NULL,
    location_id  TEXT NOT NULL,
    mes          TEXT NOT NULL,
    qtd          INTEGER NOT NULL CHECK (qtd >= 0),   -- PAs do receptivo (agentes)
    PRIMARY KEY (project_id, location_id, mes)
);

-- Linhas das abas de cada prédio do BRA_Distribution_Capacity (como no arquivo).
CREATE TABLE IF NOT EXISTS predios_arquivo (
    location_id  TEXT NOT NULL,
    ordem        INTEGER NOT NULL,
    chave        TEXT NOT NULL DEFAULT '',   -- coluna A (cliente/projeto)
    andar        TEXT NOT NULL DEFAULT '',
    descricao    TEXT NOT NULL DEFAULT '',   -- ex.: Claro Premium (44) / Claro Empresas (58/122)
    seats        INTEGER NOT NULL DEFAULT 0, -- Total Seats (Prod + TL)
    meses        TEXT NOT NULL DEFAULT '{}', -- {"2026-11": [Res, Avai], ...}
    PRIMARY KEY (location_id, ordem)
);

-- O que veio no último arquivo do CMAP importado (para comparar com o controle).
CREATE TABLE IF NOT EXISTS cmap_arquivo (
    project_id   TEXT NOT NULL,
    location_id  TEXT NOT NULL,
    dept_code    TEXT NOT NULL,
    mes          TEXT NOT NULL,
    qtd          INTEGER NOT NULL,
    PRIMARY KEY (project_id, location_id, dept_code, mes)
);

-- Carteiras ativas que NÃO estão no forecast (incluídas à mão em Frentes).
-- Os números valem para todos os meses.
CREATE TABLE IF NOT EXISTS frentes_manuais (
    lob          TEXT PRIMARY KEY REFERENCES frentes(lob) ON DELETE CASCADE,
    location_id  TEXT NOT NULL,
    andar        TEXT NOT NULL DEFAULT '',
    carga        TEXT NOT NULL,              -- 7H12 (integral) ou 6H20
    mop          INTEGER NOT NULL,           -- HCs (ativo + aviso prévio)
    home         INTEGER NOT NULL DEFAULT 0,
    staff_ic     INTEGER NOT NULL DEFAULT 0,
    staff_ho     INTEGER NOT NULL DEFAULT 0,
    ic_manha     INTEGER NOT NULL DEFAULT 0, -- só 6H20 (opcional)
    ic_tarde     INTEGER NOT NULL DEFAULT 0
);

-- Último forecast importado (uma linha por frente, local e mês).
CREATE TABLE IF NOT EXISTS forecast (
    lob          TEXT NOT NULL,
    endereco     TEXT NOT NULL,
    andar        TEXT NOT NULL,
    location_id  TEXT,                       -- NULL = endereço não reconhecido
    carga        TEXT,                       -- 6H20 ou 7H12
    fator        INTEGER NOT NULL,
    mes          TEXT NOT NULL,
    mop          REAL NOT NULL,
    home         REAL NOT NULL,
    staff_ic     REAL NOT NULL,
    staff_ho     REAL NOT NULL,
    ic_manha     REAL NOT NULL DEFAULT 0,    -- INCOMPANY MANHÃ
    ic_tarde     REAL NOT NULL DEFAULT 0     -- INCOMPANY TARDE
);

-- Visão por gestor: particularidades e staff detalhado de cada reserva (MAS + local).
-- O forecast só traz o total de staff; o detalhe é digitado na tela Gestores.
CREATE TABLE IF NOT EXISTS detalhe_reserva (
    project_id       TEXT NOT NULL,
    location_id      TEXT NOT NULL,
    particularidades TEXT NOT NULL DEFAULT '',
    supervisores     INTEGER NOT NULL DEFAULT 0,
    plan_wfm         INTEGER NOT NULL DEFAULT 0,
    qualidade        INTEGER NOT NULL DEFAULT 0,
    gerentes         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, location_id)
);
CREATE TABLE IF NOT EXISTS forecast_info (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    arquivo       TEXT NOT NULL,
    importado_em  TEXT NOT NULL,
    quem          TEXT NOT NULL,
    avisos        TEXT NOT NULL DEFAULT '',
    origem        TEXT NOT NULL DEFAULT ''  -- caminho|data do arquivo lido sozinho (caminhos.txt)
);

-- Cada vez que você marca "Lançado no CMAP".
CREATE TABLE IF NOT EXISTS lancamentos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    quando       TEXT NOT NULL,
    quem         TEXT NOT NULL,
    resv_desc    TEXT NOT NULL,
    project_id   TEXT NOT NULL,
    location_id  TEXT NOT NULL,
    detalhe      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historico (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    quando   TEXT NOT NULL,
    quem     TEXT NOT NULL,
    acao     TEXT NOT NULL,
    detalhe  TEXT NOT NULL DEFAULT ''
);
"""


# ---------------------------------------------------------------- conexão

def conectar(caminho: str) -> sqlite3.Connection:
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row          # permite usar linha["coluna"]

    con.execute("PRAGMA foreign_keys = ON")
    return con


def db() -> sqlite3.Connection:
    """Uma conexão por requisição, guardada em `g`."""
    if "db" not in g:
        g.db = conectar(current_app.config["BANCO"])
    return g.db


def iniciar(app):
    with conectar(app.config["BANCO"]) as con:
        con.executescript(ESQUEMA)
        atualizar_banco_antigo(con)
        if app.config.get("CADASTRAR_LOCAIS", True):
            cadastrar_locais_cmap(con)

    @app.teardown_appcontext
    def fechar(_erro=None):
        con = g.pop("db", None)
        if con is not None:
            con.close()


def cadastrar_locais_cmap(con):
    """Garante os locais do CMAP no banco. Não mexe nos que você já editou."""
    con.executemany(
        "INSERT OR IGNORE INTO locais (location_id, site_id, descricao, ativo) VALUES (?, ?, ?, ?)",
        [(loc, site, desc, int(loc in MEUS_LOCAIS)) for loc, site, desc in LOCAIS_CMAP])


def atualizar_banco_antigo(con):
    """
    Bancos criados na 1ª versão não têm a coluna `ativo`.
    Aqui ela é criada e já marca só os MEUS_LOCAIS como acompanhados.
    """
    def colunas(tabela):
        return {c["name"] for c in con.execute(f"PRAGMA table_info({tabela})")}

    # versão 4: gestor nas frentes e turnos no forecast
    if "gerencia" not in colunas("frentes"):
        con.execute("ALTER TABLE frentes ADD COLUMN gerencia TEXT NOT NULL DEFAULT ''")
    if "mas_sugerido" not in colunas("frentes"):
        con.execute("ALTER TABLE frentes ADD COLUMN mas_sugerido INTEGER NOT NULL DEFAULT 0")
    if "origem" not in colunas("forecast_info"):
        con.execute("ALTER TABLE forecast_info ADD COLUMN origem TEXT NOT NULL DEFAULT ''")
    for nova in ("ic_manha", "ic_tarde"):
        if nova not in colunas("forecast"):
            con.execute(f"ALTER TABLE forecast ADD COLUMN {nova} REAL NOT NULL DEFAULT 0")

    if "ativo" not in colunas("locais"):
        con.execute("ALTER TABLE locais ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")
        for linha in con.execute("SELECT location_id FROM locais").fetchall():
            con.execute("UPDATE locais SET ativo = ? WHERE location_id = ?",
                        (int(linha["location_id"] in MEUS_LOCAIS), linha["location_id"]))


def registrar(acao: str, detalhe: str = "", con: sqlite3.Connection | None = None):
    """Grava no histórico. Toda alteração passa por aqui."""
    (con or db()).execute(
        "INSERT INTO historico (quando, quem, acao, detalhe) VALUES (?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         current_app.config["USUARIO"], acao, detalhe),
    )


# ---------------------------------------------------------------- consultas
# Sempre usamos "?" nos SQL (nunca juntamos texto do usuário na consulta).
# Isso evita SQL injection.

def _ordem(local):
    """Ordena por cidade (São Paulo, Curitiba, Ponta Grossa) e depois pelo nome."""
    c = cidade(local["location_id"])
    return (ORDEM_CIDADES.index(c) if c in ORDEM_CIDADES else 99, local["descricao"])


def locais(somente_ativos: bool = False):
    sql = "SELECT * FROM locais"
    if somente_ativos:
        sql += " WHERE ativo = 1"
    return sorted(db().execute(sql).fetchall(), key=_ordem)


def reservas(mostrar_tudo: bool = False):
    sql = """
        SELECT r.*, l.site_id, l.descricao AS site_nome
        FROM reservas r JOIN locais l ON l.location_id = r.location_id
        WHERE l.ativo = 1
    """
    if not mostrar_tudo:
        sql += " AND r.status != 'Cancelado'"
    sql += " ORDER BY r.criado_em DESC, r.id DESC"
    # só as minhas carteiras (pelo cliente ou pelo nome do projeto)
    return [r for r in db().execute(sql).fetchall()
            if carteira_de(r["cliente"], r["project_name"])]


def reserva(reserva_id: int):
    return db().execute(
        """SELECT r.*, l.site_id, l.descricao AS site_nome
           FROM reservas r JOIN locais l ON l.location_id = r.location_id
           WHERE r.id = ?""", (reserva_id,)).fetchone()


def grade_assentos(reserva_id: int, janela: list[meses.Mes]):
    """
    Monta a grade da aba "Assentos": uma linha por Dept Code + Shift
    e uma coluna por mês, igual à tela do CMAP.
    """
    linhas: dict[tuple, dict] = {}
    for a in db().execute(
            "SELECT * FROM assentos WHERE reserva_id = ? ORDER BY dept_code, shift",
            (reserva_id,)):
        chave = (a["dept_code"], a["shift"])
        linha = linhas.setdefault(chave, {
            "dept_code": a["dept_code"], "dept_name": a["dept_name"],
            "shift": a["shift"], "qtd": {}})
        linha["qtd"][a["mes"]] = a["qtd"]
    # mantém só linhas com algum valor dentro da janela exibida
    chaves = {m.chave for m in janela}
    return [l for l in linhas.values() if chaves & l["qtd"].keys()]


def ocupacao(janela: list[meses.Mes]):
    """
    Painel: para cada local (agrupado por cidade), mês a mês:
      - uma linha por carteira MINHA (reservado no CMAP);
      - "Outras carteiras": o resto do prédio (não é meu, mas ocupa lugar);
      - Total reservado, Total Seats (do arquivo) e Disponível = Seats − Total.
    Status que contam: Confirmado e Fila mensal.
    Devolve (grupos, total_geral) com grupos = [{"cidade", "locais": [...], "total"}].
    """
    marcas = ",".join("?" * len(STATUS_QUE_OCUPAM))
    somas = db().execute(f"""
        SELECT r.location_id, r.project_id, r.cliente, r.project_name, a.mes, SUM(a.qtd) AS total
        FROM assentos a JOIN reservas r ON r.id = a.reserva_id
        WHERE r.status IN ({marcas})
        GROUP BY r.location_id, r.project_id, r.cliente, r.project_name, a.mes""",
        STATUS_QUE_OCUPAM).fetchall()
    receptivo = {(r["project_id"], r["location_id"], r["mes"]): r["qtd"]
                 for r in db().execute("SELECT * FROM receptivo")}
    com_receptivo = {(p, l) for p, l, _m in receptivo}                    # reservas compartilhadas
    minhas = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))   # local -> carteira -> mês
    outras = defaultdict(lambda: defaultdict(int))                        # local -> mês
    for s in somas:
        cart = carteira_de(s["cliente"], s["project_name"])     # sem cliente vai p/ "outras"
        loc, mes, total = s["location_id"], s["mes"], s["total"]
        if not cart:
            outras[loc][mes] += total
        elif eh_receptivo(s["project_name"]):                  # projeto só de receptivo
            minhas[loc][f"{cart} · receptivo"][mes] += total
        else:
            # projeto compartilhado: a parte do receptivo é o que você digitou na Reserva
            rec = min(receptivo.get((s["project_id"], loc, mes), 0), total)
            if rec:
                minhas[loc][f"{cart} · receptivo"][mes] += rec
            compartilhado = (s["project_id"], loc) in com_receptivo
            minhas[loc][f"{cart} · outbound" if compartilhado else cart][mes] += total - rec

    grupos: dict[str, dict] = {}
    geral = _vazio(janela)
    for local in locais(somente_ativos=True):
        loc, seats = local["location_id"], local["capacidade"]
        carteiras = [{"nome": nome, "res": [por_mes.get(m.chave, 0) for m in janela]}
                     for nome, por_mes in sorted(minhas[loc].items())]
        meses_local = []
        for i, m in enumerate(janela):
            mi = sum(c["res"][i] for c in carteiras)
            ou = outras[loc].get(m.chave, 0)
            meses_local.append({"minhas": mi, "outras": ou, "total": mi + ou, "seats": seats})
        info = {"local": local, "carteiras": carteiras, "meses": meses_local}
        _completar(info["meses"])
        cidade_local = cidade(loc)
        grupo = grupos.setdefault(cidade_local, {"cidade": cidade_local, "locais": [],
                                                 "total": _vazio(janela)})
        grupo["locais"].append(info)
        for alvo in (grupo["total"], geral):
            for i, x in enumerate(meses_local):
                for k in ("minhas", "outras", "total", "seats"):
                    alvo[i][k] += x[k]
    for g in grupos.values():
        _completar(g["total"])
    _completar(geral)
    return list(grupos.values()), geral


def carteiras_da_linha(chave, descricao, carteiras=None) -> list[str]:
    """
    Minhas carteiras numa linha do arquivo. Andares compartilhados listam várias
    ("Natura/Ligga/BMG/Via Varejo") — cada pedaço é conferido.
    """
    achadas = set()
    principal = carteira_de(chave, descricao, carteiras)
    if principal:
        achadas.add(principal)
    for pedaco in re.split(r"[/+]| e ", str(descricao or "")):
        c = carteira_de(pedaco, "", carteiras)
        if c:
            achadas.add(c)
    return sorted(achadas)


def _mesma_carteira(a: str, b: str) -> bool:
    """'CLARO' (parte comum, ex.: receptivo) combina com 'CLARO COBRANÇA'."""
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def painel_arquivo(janela: list[meses.Mes]):
    """
    Painel igual às abas de cada prédio do BRA_Distribution_Capacity, só com as linhas
    das MINHAS carteiras: andar, descrição, Total Seats, Res e Avai mês a mês (do arquivo).
    Quando a carteira tem receptivo (projeto RCV ou digitado na Reserva), a linha ganha
    "↳ receptivo" e "↳ outbound" logo abaixo.
    Devolve (grupos, total_geral): grupos = [{"cidade", "locais": [...], "total"}].
    """
    import json
    carteiras = minhas_carteiras()
    receptivo = _receptivo_por_carteira(janela)
    ativos = {l["location_id"]: l for l in locais(somente_ativos=True)}
    por_local = defaultdict(list)
    for r in db().execute("SELECT * FROM predios_arquivo ORDER BY location_id, ordem"):
        if r["location_id"] not in ativos:
            continue
        cart = carteiras_da_linha(r["chave"], r["descricao"], carteiras)
        valores = json.loads(r["meses"])
        res = [(valores.get(m.chave) or [None, None])[0] for m in janela]
        avai = [(valores.get(m.chave) or [None, None])[1] for m in janela]
        if not cart or (not r["seats"] and not any(res)):
            continue                                   # não é minha / linha vazia
        por_local[r["location_id"]].append({"andar": r["andar"], "descricao": r["descricao"],
                                            "carteiras": cart, "seats": r["seats"],
                                            "res": res, "avai": avai, "receptivo": None})
    grupos: dict[str, dict] = {}
    geral = _vazio_arq(janela)
    for loc, linhas in por_local.items():
        # receptivo vai na 1ª linha com reserva de cada carteira (não repete)
        usados = set()
        for l in linhas:
            if not any(l["res"]):
                continue
            rec = [0] * len(janela)
            for (rloc, rcart), por_mes in receptivo.items():
                if rloc == loc and (rloc, rcart) not in usados and \
                        any(_mesma_carteira(rcart, c) for c in l["carteiras"]):
                    usados.add((rloc, rcart))
                    rec = [a + b for a, b in zip(rec, por_mes)]
            if any(rec):
                l["receptivo"] = rec
                l["outbound"] = [(x or 0) - y for x, y in zip(l["res"], rec)]
        total = _somar_linhas(linhas, janela)
        cid = cidade(loc)
        grupo = grupos.setdefault(cid, {"cidade": cid, "locais": [], "total": _vazio_arq(janela)})
        grupo["locais"].append({"local": ativos[loc], "linhas": linhas, "total": total})
        for alvo in (grupo["total"], geral):
            _acumular(alvo, total)
    ordem = {c: i for i, c in enumerate(ORDEM_CIDADES)}
    lista = sorted(grupos.values(), key=lambda g: ordem.get(g["cidade"], 99))
    for g in lista:
        g["locais"].sort(key=lambda x: _ordem(x["local"]))
    return lista, geral


def _vazio_arq(janela):
    return {"seats": 0, "res": [0] * len(janela), "avai": [0] * len(janela)}


def _somar_linhas(linhas, janela):
    total = _vazio_arq(janela)
    for l in linhas:
        _acumular(total, l)
    return total


def _acumular(alvo, x):
    alvo["seats"] += x["seats"] or 0
    alvo["res"] = [a + (b or 0) for a, b in zip(alvo["res"], x["res"])]
    alvo["avai"] = [a + (b or 0) for a, b in zip(alvo["avai"], x["avai"])]


def _receptivo_por_carteira(janela):
    """{(local, carteira): [PAs por mês]}: projetos RCV (no CMAP) + receptivo digitado."""
    chaves = [m.chave for m in janela]
    dados = defaultdict(lambda: [0] * len(janela))
    digitado = defaultdict(dict)
    for r in db().execute("SELECT * FROM receptivo"):
        digitado[(r["project_id"], r["location_id"])][r["mes"]] = r["qtd"]
    for r in db().execute("""SELECT r.project_id, r.location_id, r.cliente, r.project_name, a.mes,
                                    SUM(a.qtd) AS q FROM assentos a JOIN reservas r ON r.id = a.reserva_id
                             WHERE r.status != 'Cancelado' AND a.dept_code = 'PRODUCAGENT-DIR'
                             GROUP BY 1, 2, 3, 4, 5"""):
        if r["mes"] not in chaves:
            continue
        cart = carteira_de(r["cliente"], r["project_name"])
        if not cart:
            continue
        if eh_receptivo(r["project_name"]):
            q = r["q"]
        else:
            q = min(digitado.get((r["project_id"], r["location_id"]), {}).get(r["mes"], 0), r["q"])
        if q:
            dados[(r["location_id"], cart)][chaves.index(r["mes"])] += q
    return dados


def _vazio(janela):
    return [{"minhas": 0, "outras": 0, "total": 0, "seats": 0} for _ in janela]


def _completar(lista):
    """Disponível e % de ocupação (só onde há Total Seats)."""
    for x in lista:
        x["disp"] = x["seats"] - x["total"] if x["seats"] else None
        x["pct"] = x["total"] / x["seats"] if x["seats"] else None


def historico(limite: int = 300):
    return db().execute(
        "SELECT * FROM historico ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
