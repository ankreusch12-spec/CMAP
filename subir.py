"""
subir.py — tela "Reserva" (o que subir no CMAP).

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

def salvar_forecast(frentes, avisos, nome_arquivo: str, origem: str = ""):
    """Substitui o forecast guardado pelo novo e atualiza a lista de frentes."""
    con = banco.db()
    # Se uma carteira incluída à mão passou a vir no forecast, o forecast assume
    # (senão ela seria contada duas vezes).
    manuais = {r["lob"] for r in con.execute("SELECT lob FROM frentes_manuais")}
    for f in frentes:
        if f["lob"] in manuais:
            con.execute("DELETE FROM frentes_manuais WHERE lob = ?", (f["lob"],))
            avisos = [*avisos, f"{f['lob']}: estava incluída à mão e agora vem no forecast — "
                               "passou a usar os números do forecast."]
    con.execute("DELETE FROM forecast")
    # Os endereços do forecast estão certos: todo prédio onde há frente passa a ser
    # acompanhado (ex.: Smiles na EZ Tower, Santander no Muricy).
    for f in frentes:
        if f["location_id"]:
            con.execute("UPDATE locais SET ativo = 1 WHERE location_id = ?", (f["location_id"],))
    for f in frentes:
        con.execute("""INSERT INTO frentes (lob, act_id, conta, gerencia) VALUES (?, ?, ?, ?)
                       ON CONFLICT (lob) DO UPDATE SET act_id = excluded.act_id,
                         conta = excluded.conta, gerencia = excluded.gerencia""",
                    (f["lob"], f["act_id"], f["conta"], f.get("gerencia", "")))
        con.executemany(
            """INSERT INTO forecast (lob, endereco, andar, location_id, carga, fator, mes,
                                     mop, home, staff_ic, staff_ho, ic_manha, ic_tarde)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(f["lob"], f["endereco"], f["andar"], f["location_id"], f["carga"], f["fator"],
              mes, v["mop"], v["home"], v["staff_ic"], v["staff_ho"],
              v.get("ic_manha", 0), v.get("ic_tarde", 0))
             for mes, v in f["valores"].items()])
    con.execute("""INSERT INTO forecast_info (id, arquivo, importado_em, quem, avisos, origem)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET arquivo = excluded.arquivo,
                     importado_em = excluded.importado_em, quem = excluded.quem,
                     avisos = excluded.avisos, origem = excluded.origem""",
                (nome_arquivo[:120], datetime.now().strftime("%Y-%m-%d %H:%M"),
                 current_app.config["USUARIO"], "\n".join(avisos), origem))
    banco.registrar("Forecast importado", f"{nome_arquivo[:120]} — {len(frentes)} frentes", con)
    con.commit()


def sincronizar(forcar: bool = False):
    """
    Forecast ligado ao arquivo (caminhos.txt): se o arquivo mudou desde a última
    leitura, importa de novo sozinho. Devolve (mensagem, tipo) para mostrar na tela,
    ou None quando não há nada a avisar.
    """
    caminho = current_app.config.get("FORECAST_CAMINHO")
    if not caminho:
        return None
    arquivo, motivos = forecast.diagnosticar(caminho)
    if not arquivo:
        return (f"Não achei o forecast em “{caminho}” (caminhos.txt): " + " ".join(motivos[:3])
                + " Até lá, vale o último forecast importado.", "erro")
    modificado = datetime.fromtimestamp(arquivo.stat().st_mtime)
    marca = f"{arquivo.resolve()}|{arquivo.stat().st_mtime_ns}"
    info = info_forecast()
    if not forcar and info and info["origem"] == marca:
        return None                                   # nada mudou
    try:
        frentes, avisos = forecast.ler(arquivo)
    except forecast.ErroForecast as erro:
        return (f"{erro} Até lá, vale o último forecast importado.", "erro")
    salvar_forecast(frentes, avisos, arquivo.name, origem=marca)
    return (f"Forecast atualizado sozinho: {arquivo.name} (salvo em "
            f"{modificado.strftime('%d/%m/%Y %H:%M')}), {len(frentes)} frentes.", "ok")


def frentes_salvas():
    """Remonta as frentes (mesmo formato de forecast.ler) a partir do banco."""
    frentes: dict[tuple, dict] = {}
    for r in banco.db().execute("SELECT f.*, fr.conta, fr.gerencia FROM forecast f "
                                "LEFT JOIN frentes fr ON fr.lob = f.lob"):
        f = frentes.setdefault((r["lob"], r["endereco"], r["andar"]), {
            "lob": r["lob"], "endereco": r["endereco"], "andar": r["andar"],
            "location_id": r["location_id"], "carga": r["carga"], "fator": r["fator"],
            "conta": r["conta"] or "", "gerencia": r["gerencia"] or "", "valores": {}})
        f["valores"][r["mes"]] = {"mop": r["mop"], "home": r["home"],
                                  "staff_ic": r["staff_ic"], "staff_ho": r["staff_ho"],
                                  "ic_manha": r["ic_manha"], "ic_tarde": r["ic_tarde"]}
    return list(frentes.values()) + frentes_manuais()


def frentes_manuais():
    """
    Carteiras incluídas à mão (fora do forecast), no mesmo formato das do forecast.
    Os números cadastrados valem para todos os meses (24 a partir do atual).
    """
    lista = []
    for r in banco.db().execute("""SELECT m.*, fr.conta, fr.gerencia FROM frentes_manuais m
                                   JOIN frentes fr ON fr.lob = m.lob"""):
        numeros = {"mop": r["mop"], "home": r["home"], "staff_ic": r["staff_ic"],
                   "staff_ho": r["staff_ho"], "ic_manha": r["ic_manha"], "ic_tarde": r["ic_tarde"]}
        lista.append({
            "lob": r["lob"], "endereco": "", "andar": r["andar"], "location_id": r["location_id"],
            "carga": r["carga"], "fator": forecast.CARGAS.get(r["carga"].lower(), 1),
            "conta": r["conta"] or "", "gerencia": r["gerencia"] or "", "manual": True,
            "valores": {m.chave: dict(numeros) for m in meses.janela(quantidade=24)}})
    return lista


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
    Lista de comparações, uma por reserva (MAS + local). Entram as reservas com forecast
    (outbound) e as que têm receptivo digitado. Cada item tem:
      resv_desc, reserva (ou None), local, lobs, carteira, tipo,
      meses: [{mes, ag_arq, ag_atual, ag_out, ag_rec, ag_novo, st_..., muda}], muda (bool)
    ag_novo = forecast outbound + receptivo (manual) = o que precisa estar no CMAP.
    """
    calculado = forecast.calcular(frentes_salvas(), de_para(), janela, _acompanho())
    receptivo = _receptivo()
    locais = {l["location_id"]: l for l in banco.locais()}
    arquivo = _do_arquivo()
    lista = []
    for project_id, location_id in set(calculado) | set(receptivo):
        b = calculado.get((project_id, location_id))
        rec = receptivo.get((project_id, location_id))
        reserva = _reserva_do_controle(project_id, location_id)
        if not b and not reserva:
            continue                                  # receptivo de reserva que não existe mais
        atual = _assentos_atuais(reserva["id"]) if reserva else {}
        # Sem STAFF no forecast desta reserva, o staff do CMAP fica como está
        # (não sugerimos zerar o TEAMLEADER-DIR só porque o forecast não traz staff).
        usa_staff = bool(b) and any(b["staff"].values())
        linhas = []
        for m in janela:
            ag_a = atual.get(forecast.DEPT_AGENTE, {}).get(m.chave, 0)
            st_a = atual.get(forecast.DEPT_STAFF, {}).get(m.chave, 0)
            ag_out = b["agentes"].get(m.chave, 0) if b else 0
            ag_rec = rec.get(m.chave, 0) if rec else 0
            ag_n = ag_out + ag_rec
            st_n = b["staff"].get(m.chave, 0) if usa_staff else st_a
            arq = arquivo.get((project_id, location_id, m.chave), {})
            linhas.append({"mes": m, "ag_atual": ag_a, "ag_out": ag_out, "ag_rec": ag_rec,
                           "ag_novo": ag_n, "st_atual": st_a, "st_novo": st_n,
                           # como veio no último arquivo do CMAP importado
                           "ag_arq": arq.get(forecast.DEPT_AGENTE, 0),
                           "st_arq": arq.get(forecast.DEPT_STAFF, 0),
                           "muda": (ag_a, st_a) != (ag_n, st_n)})
        if b:
            carteira = b["info"].get("conta") or b["info"].get("cliente") or ""
        else:
            carteira = banco.carteira_de(reserva["cliente"], reserva["project_name"]) or reserva["cliente"]
        lista.append({
            "project_id": project_id, "location_id": location_id,
            "local": locais.get(location_id),
            "reserva": reserva,
            "resv_desc": reserva["resv_desc"] if reserva else forecast.resv_desc(b["info"], location_id),
            "project_name": (reserva["project_name"] if reserva else
                             b["info"].get("project_name") or project_id),
            "lobs": sorted(b["lobs"]) if b else [],
            "carteira": carteira,
            # outbound (só forecast), receptivo (só manual) ou os dois na mesma reserva
            "tipo": "compartilhada" if b and rec else "receptivo" if rec else "outbound",
            "tem_receptivo": rec is not None,
            "meses": linhas,
            "usa_staff": usa_staff,
            "muda": any(l["muda"] for l in linhas),
        })
    lista.sort(key=lambda i: (not i["muda"], banco.cidade(i["location_id"]), i["resv_desc"]))
    return lista


def _receptivo():
    """{(MAS, local): {mês: PAs}} do receptivo digitado na tela Reserva."""
    dados = defaultdict(dict)
    for r in banco.db().execute("SELECT * FROM receptivo"):
        dados[(r["project_id"], r["location_id"])][r["mes"]] = r["qtd"]
    return dados


def salvar_receptivo(project_id: str, location_id: str, valores: dict):
    """Grava o receptivo mês a mês ({'2026-11': 90, ...}) de uma reserva."""
    con = banco.db()
    con.executemany("""INSERT INTO receptivo (project_id, location_id, mes, qtd) VALUES (?, ?, ?, ?)
                       ON CONFLICT (project_id, location_id, mes) DO UPDATE SET qtd = excluded.qtd""",
                    [(project_id, location_id, mes, qtd) for mes, qtd in valores.items()])
    banco.registrar("Receptivo salvo", f"{project_id} / {location_id}: "
                    + ", ".join(f"{meses.de_chave(m).rotulo} {q}" for m, q in sorted(valores.items())), con)
    con.commit()


def remover_receptivo(project_id: str, location_id: str):
    con = banco.db()
    con.execute("DELETE FROM receptivo WHERE project_id = ? AND location_id = ?", (project_id, location_id))
    banco.registrar("Receptivo removido", f"{project_id} / {location_id}", con)
    con.commit()


def _do_arquivo():
    """{(MAS, local, mês): {dept: qtd}} do último arquivo do CMAP importado."""
    foto = defaultdict(dict)
    for r in banco.db().execute("SELECT * FROM cmap_arquivo"):
        foto[(r["project_id"], r["location_id"], r["mes"])][r["dept_code"]] = r["qtd"]
    return foto


def tem_arquivo() -> bool:
    return bool(banco.db().execute("SELECT 1 FROM cmap_arquivo LIMIT 1").fetchone())


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
        cliente = next((info[l]["conta"] or info[l]["cliente"] for l in item["lobs"] if l in info), "")
        reserva_id = con.execute(
            """INSERT INTO reservas (resv_desc, project_id, project_name, cliente, location_id,
                                     status, criado_em, criado_por)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["resv_desc"], project_id, item["project_name"], cliente.upper(),
             location_id, STATUS_NOVA, date.today().isoformat(), usuario)).lastrowid

    chaves = [m.chave for m in janela]
    marcas = ",".join("?" * len(chaves))
    depts = [forecast.DEPT_AGENTE] + ([forecast.DEPT_STAFF] if item["usa_staff"] else [])
    con.execute(f"""DELETE FROM assentos WHERE reserva_id = ? AND dept_code IN ({",".join("?" * len(depts))})
                    AND mes IN ({marcas})""",
                (reserva_id, *depts, *chaves))
    nomes = {forecast.DEPT_AGENTE: "COGS (SITE) Production Agent Direct",
             forecast.DEPT_STAFF: "COGS (SITE) Team Leader Direct"}
    mudancas = []
    for l in item["meses"]:
        for dept, qtd in ((forecast.DEPT_AGENTE, l["ag_novo"]), (forecast.DEPT_STAFF, l["st_novo"])):
            if qtd and dept in depts:
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
