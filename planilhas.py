"""
planilhas.py — entrada e saída de Excel no formato do CMAP.

IMPORTAR: lê o relatório exportado do CMAP (o mesmo que alimenta a aba
"12 month forecast" da planilha de capacidade). As colunas esperadas são:

    Country | Location ID | Site ID | Site | Client | Project ID | Project |
    Dept | Shift | Type | Eff Date | Qty

EXPORTAR: gera um Excel com as reservas do controle no MESMO formato,
pronto para conferir/lançar no CMAP (e que pode ser importado de volta).
"""
from collections import defaultdict
from datetime import date
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import banco
import meses

# Nome "bonito" de cada Dept Code, como aparece na aba Assentos do CMAP.
NOMES_DEPT = {
    "PRODUCAGENT-DIR": "COGS (SITE) Production Agent Direct",
    "TEAMLEADER-DIR": "COGS (SITE) Team Leader Direct",
}

# Cabeçalho do arquivo -> nome do campo aqui no código.
COLUNAS = {
    "country": "pais", "location id": "location_id", "site id": "site_id",
    "site": "site", "client": "cliente", "project id": "project_id",
    "project": "project", "dept": "dept", "dept name": "dept_name",
    "shift": "shift", "type": "tipo", "eff date": "eff_date", "qty": "qty",
    "resv desc": "resv_desc", "status": "status",
}
OBRIGATORIAS = {"location_id", "project_id", "dept", "eff_date", "qty"}


class ErroPlanilha(Exception):
    """Problema no arquivo enviado (mensagem mostrada para o usuário)."""


# ================================================================ IMPORTAR

def _achar_cabecalho(aba):
    """Procura, nas 15 primeiras linhas, a linha que tem os nomes das colunas."""
    for n, linha in enumerate(aba.iter_rows(max_row=15, values_only=True), start=1):
        nomes = {str(v).strip().lower(): i for i, v in enumerate(linha) if v is not None}
        mapa = {COLUNAS[k]: i for k, i in nomes.items() if k in COLUNAS}
        if OBRIGATORIAS <= mapa.keys():
            return n, mapa
    return None, None


def ler(arquivo, somente_pais: str | None = "Brazil"):
    """
    Lê o Excel e devolve uma lista de linhas (dicts) já limpas.
    `arquivo` pode ser um caminho ou um arquivo aberto.
    """
    try:
        # read_only: leitura rápida e segura; data_only: valores, não fórmulas.
        livro = load_workbook(arquivo, read_only=True, data_only=True)
    except Exception as erro:  # arquivo corrompido, não é xlsx, etc.
        raise ErroPlanilha("Não consegui abrir o arquivo. Ele é um .xlsx válido?") from erro

    try:
        for aba in livro.worksheets:
            n_cab, mapa = _achar_cabecalho(aba)
            if not mapa:
                continue
            linhas, avisos = [], []
            for n, valores in enumerate(aba.iter_rows(min_row=n_cab + 1, values_only=True),
                                        start=n_cab + 1):
                def campo(nome, padrao=""):
                    i = mapa.get(nome)
                    v = valores[i] if i is not None and i < len(valores) else None
                    return padrao if v is None else v

                if not campo("location_id") or not campo("project_id"):
                    continue                                   # linha vazia
                if somente_pais and "pais" in mapa and str(campo("pais")).strip() != somente_pais:
                    continue
                try:
                    mes = meses.de_valor(campo("eff_date"))
                    qtd = int(campo("qty", 0))
                    if qtd < 0:
                        raise ValueError
                except (ValueError, IndexError):
                    avisos.append(f"Linha {n}: data ou quantidade inválida — ignorada.")
                    continue
                dept = str(campo("dept")).strip().upper()
                linhas.append({
                    "location_id": str(campo("location_id")).strip(),
                    "site_id": str(campo("site_id")).strip(),
                    "site": str(campo("site")).strip(),
                    "cliente": str(campo("cliente")).strip(),
                    "project_id": str(campo("project_id")).strip(),
                    "project": str(campo("project")).strip(),
                    "dept": dept,
                    "dept_name": str(campo("dept_name")).strip() or NOMES_DEPT.get(dept, ""),
                    "shift": str(campo("shift", "DED")).strip().upper() or "DED",
                    "resv_desc": str(campo("resv_desc")).strip(),
                    "status": str(campo("status")).strip(),
                    "mes": mes.chave,
                    "qtd": qtd,
                })
            return linhas, avisos
    finally:
        livro.close()

    raise ErroPlanilha(
        "Não encontrei as colunas do CMAP (Location ID, Project ID, Dept, Eff Date, Qty). "
        "Use o relatório exportado do CMAP ou um arquivo exportado por este controle.")


def gravar(linhas, usuario: str):
    """
    Grava as linhas lidas no banco.
    - Local que não existe é criado (depois é só ajustar a capacidade).
    - A reserva é identificada por Project ID + Location ID (+ Resv. Desc. se houver).
    - A quantidade de cada Dept/Shift/mês é SUBSTITUÍDA pela do arquivo.
    """
    con = banco.db()
    hoje = date.today().isoformat()
    resumo = {"locais": 0, "reservas": 0, "valores": 0, "ignoradas": 0}

    # Só entram os locais que eu acompanho (marcados em Locais, ou da lista
    # MEUS_LOCAIS se o local ainda não existe). O resto é ignorado.
    cadastrados = {l["location_id"]: l["ativo"] for l in banco.locais()}

    def acompanho(location_id):
        if location_id in cadastrados:
            return bool(cadastrados[location_id])
        return location_id in banco.MEUS_LOCAIS

    total = len(linhas)
    linhas = [l for l in linhas if acompanho(l["location_id"])]
    resumo["ignoradas"] = total - len(linhas)

    # Soma linhas repetidas (mesmo projeto/local/dept/shift/mês).
    somado = defaultdict(int)
    info = {}
    for l in linhas:
        chave_res = (l["project_id"], l["location_id"], l["resv_desc"])
        somado[(chave_res, l["dept"], l["shift"], l["mes"])] += l["qtd"]
        info.setdefault(chave_res, l)
        info.setdefault(("dept", l["dept"]), l["dept_name"])

    ids = {}
    for chave_res, l in info.items():
        if chave_res[0] == "dept":
            continue
        if not con.execute("SELECT 1 FROM locais WHERE location_id = ?",
                           (l["location_id"],)).fetchone():
            con.execute("INSERT INTO locais (location_id, site_id, descricao) VALUES (?, ?, ?)",
                        (l["location_id"], l["site_id"], l["site"] or l["location_id"]))
            resumo["locais"] += 1

        sql = "SELECT id FROM reservas WHERE project_id = ? AND location_id = ?"
        args = [l["project_id"], l["location_id"]]
        if l["resv_desc"]:
            sql += " AND resv_desc = ?"
            args.append(l["resv_desc"])
        achada = con.execute(sql + " ORDER BY id LIMIT 1", args).fetchone()
        if achada:
            ids[chave_res] = achada["id"]
        else:
            status = l["status"] if l["status"] in banco.STATUS else "Confirmado"
            desc = l["resv_desc"] or f"{l['cliente'] or l['project_id']}_{l['site_id']}".upper()
            cur = con.execute(
                """INSERT INTO reservas (resv_desc, project_id, project_name, cliente,
                       location_id, status, criado_em, criado_por)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (desc, l["project_id"], l["project"] or l["project_id"], l["cliente"],
                 l["location_id"], status, hoje, usuario))
            ids[chave_res] = cur.lastrowid
            resumo["reservas"] += 1

    for (chave_res, dept, shift, mes), qtd in somado.items():
        con.execute(
            """INSERT INTO assentos (reserva_id, dept_code, dept_name, shift, mes, qtd)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (reserva_id, dept_code, shift, mes)
               DO UPDATE SET qtd = excluded.qtd""",
            (ids[chave_res], dept, info[("dept", dept)], shift, mes, qtd))
        resumo["valores"] += 1

    banco.registrar("Importação", f"{resumo['reservas']} reservas novas, "
                    f"{resumo['locais']} locais novos, {resumo['valores']} valores, "
                    f"{resumo['ignoradas']} linhas de outros locais ignoradas", con)
    con.commit()
    return resumo


# ================================================================ EXPORTAR

def _texto(valor):
    """
    Proteção contra "fórmula escondida": se um texto começa com = + - @,
    o Excel poderia executá-lo como fórmula. Colocamos um ' na frente.
    """
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@"):
        return "'" + valor
    return valor


def _aba(livro, titulo, cabecalho, linhas, primeira=False):
    aba = livro.active if primeira else livro.create_sheet()
    aba.title = titulo
    aba.append(cabecalho)
    for c in aba[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="C9C9F0")
    for linha in linhas:
        aba.append([_texto(v) for v in linha])
    for i, nome in enumerate(cabecalho, start=1):
        aba.column_dimensions[get_column_letter(i)].width = max(10, len(str(nome)) + 4)
    aba.freeze_panes = "A2"
    return aba


def exportar(janela: list[meses.Mes]) -> BytesIO:
    con = banco.db()
    livro = Workbook()

    # Aba 1 — lista de reservas (igual à tela "Ver reserva").
    reservas = banco.reservas(mostrar_tudo=True)
    _aba(livro, "Reservas",
         ["Resv. Desc.", "ID do projeto", "Nome do projeto", "ID do site", "Nome do site",
          "Identificação do local", "Data de criação", "Criado por", "Status"],
         [[r["resv_desc"], r["project_id"], r["project_name"], r["site_id"], r["site_nome"],
           r["location_id"], r["criado_em"], r["criado_por"], r["status"]] for r in reservas],
         primeira=True)

    # Aba 2 — grade de assentos por mês (igual à aba "Assentos" do CMAP).
    grade = []
    for r in reservas:
        for l in banco.grade_assentos(r["id"], janela):
            grade.append([r["resv_desc"], f"{r['project_id']}-{r['project_name']}",
                          f"{r['site_id']}({r['location_id']}) {r['site_nome']}",
                          l["dept_code"], l["dept_name"], l["shift"]]
                         + [l["qtd"].get(m.chave, 0) for m in janela])
    _aba(livro, "Assentos",
         ["Resv. Desc.", "Project", "Site", "Dept Code", "Dept Name", "Shift"]
         + [m.rotulo for m in janela], grade)

    # Aba 3 — formato "relatório do CMAP" (uma linha por mês). Pode ser reimportado.
    longas = con.execute("""
        SELECT l.location_id, l.site_id, l.descricao, r.cliente, r.project_id,
               r.project_name, a.dept_code, a.dept_name, a.shift, a.mes, a.qtd,
               r.resv_desc, r.status
        FROM assentos a JOIN reservas r ON r.id = a.reserva_id
        JOIN locais l ON l.location_id = r.location_id
        WHERE l.ativo = 1
        ORDER BY l.descricao, r.project_id, a.dept_code, a.mes""").fetchall()
    aba = _aba(livro, "Relatorio CMAP",
               ["Country", "Location ID", "Site ID", "Site", "Client", "Project ID", "Project",
                "Dept", "Dept Name", "Shift", "Eff Date", "Qty", "Resv Desc", "Status"],
               [["Brazil", x["location_id"], x["site_id"], x["descricao"], x["cliente"],
                 x["project_id"], x["project_name"], x["dept_code"], x["dept_name"], x["shift"],
                 meses.de_chave(x["mes"]).primeiro_dia, x["qtd"], x["resv_desc"], x["status"]]
                for x in longas])
    for c in aba["K"][1:]:
        c.number_format = "mm/dd/yyyy"

    saida = BytesIO()
    livro.save(saida)
    saida.seek(0)
    return saida
