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
}

# Cidade de cada local, pelo pedaço do meio do código (BR-CUR-... = Curitiba).
# A ordem aqui é a ordem dos grupos no painel.
CIDADES = {"SAO": "São Paulo", "BAR": "São Paulo", "CUR": "Curitiba", "PON": "Ponta Grossa"}
ORDEM_CIDADES = ["São Paulo", "Curitiba", "Ponta Grossa"]


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

    @app.teardown_appcontext
    def fechar(_erro=None):
        con = g.pop("db", None)
        if con is not None:
            con.close()


def atualizar_banco_antigo(con):
    """
    Bancos criados na 1ª versão não têm a coluna `ativo`.
    Aqui ela é criada e já marca só os MEUS_LOCAIS como acompanhados.
    """
    colunas = {c["name"] for c in con.execute("PRAGMA table_info(locais)")}
    if "ativo" not in colunas:
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
