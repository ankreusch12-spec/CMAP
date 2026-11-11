"""
subir.py — "O que subir no CMAP".

Compara, para cada reserva (MAS + local) e cada mês:
    o que está no controle (= o que já está lançado no CMAP)
    × o que o forecast pede (regras em forecast.py)
e, quando você marca "Lançado no CMAP", grava os números novos no controle
e registra o lançamento.
"""
from collections import defaultdict
from datetime import date, datetime

from flask import current_app

import banco
import forecast
import meses

STATUS_NOVA = "Confirmado"


# ---------------------------------------------------------------- guardar o forecast

def salvar_forecast(frentes, avisos, nome_arquivo: str):
    """Substitui o forecast guardado pelo novo e atualiza a lista de frentes."""
    con = banco.db()
    con.execute("DELETE FROM forecast")
    for f in frentes:
        con.execute("""INSERT INTO frentes (lob, act_id, conta) VALUES (?, ?, ?)
                       ON CONFLICT (lob) DO UPDATE SET act_id = excluded.act_id,
                                                       conta = excluded.conta""",
                    (f["lob"], f["act_id"], f["conta"]))
        con.executemany(
            """INSERT INTO forecast (lob, endereco, andar, location_id, carga, fator, mes,
                                     mop, home, staff_ic, staff_ho)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(f["lob"], f["endereco"], f["andar"], f["location_id"], f["carga"], f["fator"],
              mes, v["mop"], v["home"], v["staff_ic"], v["staff_ho"])
             for mes, v in f["valores"].items()])
    con.execute("""INSERT INTO forecast_info (id, arquivo, importado_em, quem, avisos)
                   VALUES (1, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET arquivo = excluded.arquivo,
                     importado_em = excluded.importado_em, quem = excluded.quem,
                     avisos = excluded.avisos""",
                (nome_arquivo[:120], datetime.now().strftime("%Y-%m-%d %H:%M"),
                 current_app.config["USUARIO"], "\n".join(avisos)))
    banco.registrar("Forecast importado", f"{nome_arquivo[:120]} — {len(frentes)} frentes", con)
    con.commit()


def frentes_salvas():
    """Remonta as frentes (mesmo formato de forecast.ler) a partir do banco."""
    frentes: dict[tuple, dict] = {}
    for r in banco.db().execute("SELECT f.*, fr.conta FROM forecast f "
                                "LEFT JOIN frentes fr ON fr.lob = f.lob"):
        f = frentes.setdefault((r["lob"], r["endereco"], r["andar"]), {
            "lob": r["lob"], "endereco": r["endereco"], "andar": r["andar"],
            "location_id": r["location_id"], "carga": r["carga"], "fator": r["fator"],
            "conta": r["conta"] or "", "valores": {}})
        f["valores"][r["mes"]] = {"mop": r["mop"], "home": r["home"],
                                  "staff_ic": r["staff_ic"], "staff_ho": r["staff_ho"]}
    return list(frentes.values())


def de_para() -> dict:
    return {r["lob"]: dict(r) for r in banco.db().execute("SELECT * FROM frentes")}


def info_forecast():
    return banco.db().execute("SELECT * FROM forecast_info WHERE id = 1").fetchone()


def _acompanho():
    ativos = {l["location_id"] for l in banco.locais(somente_ativos=True)}
    return lambda location_id: location_id in ativos


# ---------------------------------------------------------------- comparar

def _reserva_do_controle(project_id, location_id):
    return banco.db().execute(
        """SELECT * FROM reservas WHERE project_id = ? AND location_id = ?
           AND status != 'Cancelado' ORDER BY id LIMIT 1""",
        (project_id, location_id)).fetchone()


def _assentos_atuais(reserva_id) -> dict:
    """{dept: {mes: qtd}} somando todos os Shifts."""
    atual = defaultdict(lambda: defaultdict(int))
    for a in banco.db().execute("SELECT dept_code, mes, qtd FROM assentos WHERE reserva_id = ?",
                                (reserva_id,)):
        atual[a["dept_code"]][a["mes"]] += a["qtd"]
    return atual


def itens(janela: list[meses.Mes]):
    """
    Lista de comparações, uma por MAS + local. Cada item tem:
      chave, resv_desc, reserva (ou None), local, lobs,
      meses: [{mes, ag_atual, ag_novo, st_atual, st_novo, muda}], muda (bool)
    """
    calculado = forecast.calcular(frentes_salvas(), de_para(), janela, _acompanho())
    locais = {l["location_id"]: l for l in banco.locais()}
    lista = []
    for (project_id, location_id), b in calculado.items():
        reserva = _reserva_do_controle(project_id, location_id)
        atual = _assentos_atuais(reserva["id"]) if reserva else {}
        linhas = []
        for m in janela:
            ag_a = atual.get(forecast.DEPT_AGENTE, {}).get(m.chave, 0)
            st_a = atual.get(forecast.DEPT_STAFF, {}).get(m.chave, 0)
            ag_n = b["agentes"].get(m.chave, 0)
            st_n = b["staff"].get(m.chave, 0)
            linhas.append({"mes": m, "ag_atual": ag_a, "ag_novo": ag_n,
                           "st_atual": st_a, "st_novo": st_n,
                           "muda": (ag_a, st_a) != (ag_n, st_n)})
        lista.append({
            "project_id": project_id, "location_id": location_id,
            "local": locais.get(location_id),
            "reserva": reserva,
            "resv_desc": reserva["resv_desc"] if reserva else forecast.resv_desc(b["info"], location_id),
            "project_name": (reserva["project_name"] if reserva else
                             b["info"].get("project_name") or project_id),
            "lobs": sorted(b["lobs"]),
            "meses": linhas,
            "muda": any(l["muda"] for l in linhas),
        })
    lista.sort(key=lambda i: (not i["muda"], banco.cidade(i["location_id"]), i["resv_desc"]))
    return lista


def pendencias_de_para():
    """Frentes do forecast que ainda não têm MAS (não entram no cálculo)."""
    return banco.db().execute(
        """SELECT DISTINCT fr.* FROM frentes fr JOIN forecast f ON f.lob = fr.lob
           WHERE fr.project_id = '' ORDER BY fr.conta, fr.lob""").fetchall()


# ---------------------------------------------------------------- lançar

def lancar(project_id: str, location_id: str, janela: list[meses.Mes]) -> str | None:
    """
    Você já lançou no CMAP: copia os números do forecast para o controle
    (criando a reserva se não existir) e registra o lançamento.
    Devolve o Resv. Desc., ou None se não houver nada a lançar.
    """
    item = next((i for i in itens(janela)
                 if (i["project_id"], i["location_id"]) == (project_id, location_id)), None)
    if not item or not item["muda"]:
        return None
    con = banco.db()
    usuario = current_app.config["USUARIO"]
    reserva = item["reserva"]
    if reserva:
        reserva_id = reserva["id"]
    else:
        info = de_para()
        cliente = next((info[l]["cliente"] or info[l]["conta"] for l in item["lobs"] if l in info), "")
        reserva_id = con.execute(
            """INSERT INTO reservas (resv_desc, project_id, project_name, cliente, location_id,
                                     status, criado_em, criado_por)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["resv_desc"], project_id, item["project_name"], cliente.upper(),
             location_id, STATUS_NOVA, date.today().isoformat(), usuario)).lastrowid

    chaves = [m.chave for m in janela]
    marcas = ",".join("?" * len(chaves))
    con.execute(f"""DELETE FROM assentos WHERE reserva_id = ? AND dept_code IN (?, ?)
                    AND mes IN ({marcas})""",
                (reserva_id, forecast.DEPT_AGENTE, forecast.DEPT_STAFF, *chaves))
    nomes = {forecast.DEPT_AGENTE: "COGS (SITE) Production Agent Direct",
             forecast.DEPT_STAFF: "COGS (SITE) Team Leader Direct"}
    mudancas = []
    for l in item["meses"]:
        for dept, qtd in ((forecast.DEPT_AGENTE, l["ag_novo"]), (forecast.DEPT_STAFF, l["st_novo"])):
            if qtd:
                con.execute("""INSERT INTO assentos (reserva_id, dept_code, dept_name, shift, mes, qtd)
                               VALUES (?, ?, ?, 'DED', ?, ?)""",
                            (reserva_id, dept, nomes[dept], l["mes"].chave, qtd))
        if l["muda"]:
            mudancas.append(f"{l['mes'].rotulo}: agentes {l['ag_atual']}→{l['ag_novo']}"
                            f", staff {l['st_atual']}→{l['st_novo']}")
    detalhe = "; ".join(mudancas)
    con.execute("""INSERT INTO lancamentos (quando, quem, resv_desc, project_id, location_id, detalhe)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now().strftime("%Y-%m-%d %H:%M"), usuario, item["resv_desc"],
                 project_id, location_id, detalhe))
    banco.registrar("Lançado no CMAP", f"{item['resv_desc']} — {detalhe}", con)
    con.commit()
    return item["resv_desc"]


def lancamentos(limite: int = 50):
    return banco.db().execute("SELECT * FROM lancamentos ORDER BY id DESC LIMIT ?",
                              (limite,)).fetchall()
