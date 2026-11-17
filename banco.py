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
import sqlite3
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
    gerencia      TEXT NOT NULL DEFAULT ''  -- gestor (coluna GERENCIA do forecast)
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
    return db().execute(sql).fetchall()


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
    Painel: para cada local e mês -> reservado, disponível e % ocupação,
    agrupado por cidade com subtotal (igual à aba Summary da planilha).
    Mesma conta da planilha: Avai = Total Seats - Res.

    Devolve (grupos, total_geral):
      grupos = [{"cidade": "Curitiba", "linhas": [...], "totais": [...]}, ...]
    """
    marcas = ",".join("?" * len(STATUS_QUE_OCUPAM))
    somas = db().execute(f"""
        SELECT r.location_id, a.mes, SUM(a.qtd) AS total
        FROM assentos a JOIN reservas r ON r.id = a.reserva_id
        WHERE r.status IN ({marcas})
        GROUP BY r.location_id, a.mes""", STATUS_QUE_OCUPAM).fetchall()
    reservado = {(s["location_id"], s["mes"]): s["total"] for s in somas}

    grupos: dict[str, dict] = {}
    geral = _totais_vazios(janela)
    for local in locais(somente_ativos=True):
        cap = local["capacidade"]
        celulas = []
        for m in janela:
            res = reservado.get((local["location_id"], m.chave), 0)
            celulas.append({"res": res,
                            "disp": cap - res if cap else None,
                            "pct": res / cap if cap else None})
        grupo = grupos.setdefault(cidade(local["location_id"]), {
            "cidade": cidade(local["location_id"]), "linhas": [],
            "totais": _totais_vazios(janela)})
        grupo["linhas"].append({"local": local, "celulas": celulas})
        if cap:                              # só soma no total quem tem capacidade
            for i, c in enumerate(celulas):
                for t in (grupo["totais"][i], geral[i]):
                    t["cap"] += cap
                    t["res"] += c["res"]

    for t in [*geral, *(t for g in grupos.values() for t in g["totais"])]:
        t["disp"] = t["cap"] - t["res"]
        t["pct"] = t["res"] / t["cap"] if t["cap"] else None
    return list(grupos.values()), geral


def _totais_vazios(janela):
    return [{"cap": 0, "res": 0} for _ in janela]


def historico(limite: int = 300):
    return db().execute(
        "SELECT * FROM historico ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
