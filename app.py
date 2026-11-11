"""
Controle CMAP — página web local para organizar as reservas de assentos
no mesmo padrão do CMAP (Archibus).

Como rodar (detalhes no README.md):
    python app.py
e abrir no navegador:  http://127.0.0.1:5000

Mapa do código:
    app.py        -> as páginas (rotas) e o que cada uma faz   <- você está aqui
    banco.py      -> banco de dados (SQLite) e consultas
    forecast.py   -> lê o FORECAST OFICIAL e aplica as regras (6H20 ÷ 2, arredonda p/ cima)
    subir.py      -> "O que subir no CMAP": forecast × controle e os lançamentos
    planilhas.py  -> importar / exportar Excel no formato do CMAP
    meses.py      -> janela de 12 meses (Nov-2026 ... Oct-2027)
    seguranca.py  -> proteções (CSRF, só acesso local, cabeçalhos)
    templates/    -> o HTML de cada página
    static/       -> estilo (CSS) e o pouco de JavaScript
"""
import os
import re
from datetime import date

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_file, url_for)

import banco
import forecast
import meses
import planilhas
import seguranca
import subir

# Regras simples para validar o que é digitado.
RE_CODIGO = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{0,39}$")     # Dept Code, Shift, IDs
LIMITE_TEXTO = 120


def criar_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        BANCO=os.path.join(app.instance_path, "cmap.db"),
        SECRET_KEY=seguranca.chave_secreta(app.instance_path),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,          # upload de no máximo 20 MB
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        USUARIO=os.environ.get("CMAP_USUARIO", "Usuário local"),
    )
    if config:
        app.config.update(config)
    banco.iniciar(app)
    seguranca.iniciar(app)
    registrar_rotas(app)

    # Deixa estes itens disponíveis em todos os templates.
    app.jinja_env.globals.update(STATUS=banco.STATUS, restrito=meses.restrito)
    return app


def texto(campo: str, obrigatorio: bool = True) -> str:
    """Pega um campo do formulário, tira espaços e valida o tamanho."""
    valor = request.form.get(campo, "").strip()
    if obrigatorio and not valor:
        raise ValueError(f"Preencha o campo “{campo}”.")
    if len(valor) > LIMITE_TEXTO:
        raise ValueError(f"O campo “{campo}” passou de {LIMITE_TEXTO} caracteres.")
    return valor


def codigo(campo: str) -> str:
    valor = texto(campo).upper()
    if not RE_CODIGO.match(valor):
        raise ValueError(f"“{campo}” aceita só letras, números, - e _ (ex.: PRODUCAGENT-DIR).")
    return valor


def registrar_rotas(app: Flask):

    # ------------------------------------------------------------ PAINEL
    @app.get("/")
    def painel():
        janela = meses.janela()
        grupos, totais = banco.ocupacao(janela)
        return render_template("painel.html", janela=janela, grupos=grupos, totais=totais)

    # ------------------------------------------------------------ LOCAIS (de-para)
    @app.get("/locais")
    def locais():
        todos = banco.locais()
        return render_template("locais.html",
                               meus=[l for l in todos if l["ativo"]],
                               outros=[l for l in todos if not l["ativo"]])

    @app.post("/locais")
    def salvar_local():
        try:
            location_id = codigo("location_id")
            site_id = texto("site_id", obrigatorio=False).upper()
            descricao = texto("descricao")
            capacidade = int(request.form.get("capacidade") or 0)
            if not 0 <= capacidade <= 100000:
                raise ValueError("Capacidade inválida.")
            ativo = 1 if request.form.get("ativo") else 0
        except ValueError as erro:
            flash(str(erro), "erro")
            return redirect(url_for("locais"))
        con = banco.db()
        con.execute("""INSERT INTO locais (location_id, site_id, descricao, capacidade, ativo)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT (location_id) DO UPDATE SET
                         site_id = excluded.site_id, descricao = excluded.descricao,
                         capacidade = excluded.capacidade, ativo = excluded.ativo""",
                    (location_id, site_id, descricao, capacidade, ativo))
        banco.registrar("Local salvo", f"{location_id} — {descricao} — capacidade {capacidade}"
                                       f" — {'acompanho' if ativo else 'não acompanho'}")
        con.commit()
        flash(f"Local {location_id} salvo.", "ok")
        return redirect(url_for("locais"))

    # ------------------------------------------------------------ RESERVAS
    @app.get("/reservas")
    def reservas():
        tudo = request.args.get("tudo") == "1"
        return render_template("reservas.html", reservas=banco.reservas(tudo), tudo=tudo)

    @app.get("/reservas/nova")
    def nova_reserva():
        return render_template("reserva.html", r=None, locais=banco.locais(somente_ativos=True),
                               janela=meses.janela(), grade=[])

    @app.post("/reservas/nova")
    def criar_reserva():
        try:
            dados = ler_perfil()
        except ValueError as erro:
            flash(str(erro), "erro")
            return redirect(url_for("nova_reserva"))
        con = banco.db()
        cur = con.execute(
            """INSERT INTO reservas (resv_desc, project_id, project_name, cliente,
                   location_id, status, criado_em, criado_por)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (*dados, date.today().isoformat(), app.config["USUARIO"]))
        banco.registrar("Reserva criada", f"{dados[0]} ({dados[1]})")
        con.commit()
        flash("Reserva criada. Agora preencha os assentos.", "ok")
        return redirect(url_for("ver_reserva", reserva_id=cur.lastrowid, aba="assentos"))

    @app.get("/reservas/<int:reserva_id>")
    def ver_reserva(reserva_id):
        r = banco.reserva(reserva_id) or abort(404)
        janela = meses.janela()
        return render_template("reserva.html", r=r, locais=banco.locais(somente_ativos=True),
                               janela=janela,
                               grade=banco.grade_assentos(reserva_id, janela),
                               aba=request.args.get("aba", "perfil"))

    @app.post("/reservas/<int:reserva_id>/perfil")
    def salvar_perfil(reserva_id):
        banco.reserva(reserva_id) or abort(404)
        try:
            dados = ler_perfil()
        except ValueError as erro:
            flash(str(erro), "erro")
            return redirect(url_for("ver_reserva", reserva_id=reserva_id))
        con = banco.db()
        con.execute("""UPDATE reservas SET resv_desc=?, project_id=?, project_name=?,
                         cliente=?, location_id=?, status=? WHERE id=?""",
                    (*dados, reserva_id))
        banco.registrar("Perfil alterado", f"{dados[0]} — status {dados[5]}")
        con.commit()
        flash("Perfil salvo.", "ok")
        return redirect(url_for("ver_reserva", reserva_id=reserva_id))

    @app.post("/reservas/<int:reserva_id>/assentos")
    def salvar_assentos(reserva_id):
        r = banco.reserva(reserva_id) or abort(404)
        janela = meses.janela()
        try:
            linhas = ler_grade(janela)
        except ValueError as erro:
            flash(str(erro), "erro")
            return redirect(url_for("ver_reserva", reserva_id=reserva_id, aba="assentos"))

        con = banco.db()
        chaves = [m.chave for m in janela]
        marcas = ",".join("?" * len(chaves))
        # Regrava a janela exibida; meses fora dela ficam como estão.
        con.execute(f"DELETE FROM assentos WHERE reserva_id = ? AND mes IN ({marcas})",
                    (reserva_id, *chaves))
        for l in linhas:
            for mes, qtd in l["qtd"].items():
                if qtd:
                    con.execute("""INSERT INTO assentos
                                   (reserva_id, dept_code, dept_name, shift, mes, qtd)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (reserva_id, l["dept_code"], l["dept_name"], l["shift"], mes, qtd))
        banco.registrar("Assentos alterados", f"{r['resv_desc']} — {len(linhas)} linha(s)")
        con.commit()
        flash("Assentos salvos.", "ok")
        return redirect(url_for("ver_reserva", reserva_id=reserva_id, aba="assentos"))

    @app.post("/reservas/<int:reserva_id>/copia")
    def copiar_reserva(reserva_id):
        """Igual ao link "Cópia" do CMAP: duplica a reserva como Rascunho."""
        r = banco.reserva(reserva_id) or abort(404)
        con = banco.db()
        cur = con.execute(
            """INSERT INTO reservas (resv_desc, project_id, project_name, cliente,
                   location_id, status, criado_em, criado_por)
               VALUES (?, ?, ?, ?, ?, 'Rascunho', ?, ?)""",
            (r["resv_desc"] + "_COPIA", r["project_id"], r["project_name"], r["cliente"],
             r["location_id"], date.today().isoformat(), app.config["USUARIO"]))
        con.execute("""INSERT INTO assentos (reserva_id, dept_code, dept_name, shift, mes, qtd)
                       SELECT ?, dept_code, dept_name, shift, mes, qtd
                       FROM assentos WHERE reserva_id = ?""", (cur.lastrowid, reserva_id))
        banco.registrar("Reserva copiada", f"{r['resv_desc']} -> {r['resv_desc']}_COPIA")
        con.commit()
        flash("Cópia criada como Rascunho. Ajuste o nome e o local.", "ok")
        return redirect(url_for("ver_reserva", reserva_id=cur.lastrowid))

    @app.post("/reservas/<int:reserva_id>/excluir")
    def excluir_reserva(reserva_id):
        r = banco.reserva(reserva_id) or abort(404)
        con = banco.db()
        con.execute("DELETE FROM reservas WHERE id = ?", (reserva_id,))
        banco.registrar("Reserva excluída", f"{r['resv_desc']} ({r['project_id']})")
        con.commit()
        flash(f"Reserva {r['resv_desc']} excluída.", "ok")
        return redirect(url_for("reservas"))

    # ------------------------------------------------------------ IMPORTAR / EXPORTAR
    @app.get("/importar")
    def importar():
        return render_template("importar.html")

    @app.post("/importar")
    def receber_importacao():
        arquivo = arquivo_xlsx()
        if not arquivo:
            return redirect(url_for("importar"))
        try:
            linhas, avisos = planilhas.ler(arquivo.stream)
        except planilhas.ErroPlanilha as erro:
            flash(str(erro), "erro")
            return redirect(url_for("importar"))
        if not linhas:
            flash("Nenhuma linha encontrada para importar.", "erro")
            return redirect(url_for("importar"))
        resumo = planilhas.gravar(linhas, app.config["USUARIO"])
        flash(f"Importado: {resumo['reservas']} reservas novas, {resumo['locais']} locais "
              f"novos e {resumo['valores']} valores mês a mês. "
              f"{resumo['ignoradas']} linha(s) de locais que você não acompanha foram ignoradas.",
              "ok")
        for aviso in avisos[:10]:
            flash(aviso, "erro")
        return redirect(url_for("reservas"))

    @app.get("/exportar")
    def exportar():
        arquivo = planilhas.exportar(meses.janela())
        nome = f"controle_cmap_{date.today().isoformat()}.xlsx"
        return send_file(arquivo, as_attachment=True, download_name=nome,
                         mimetype="application/vnd.openxmlformats-officedocument."
                                  "spreadsheetml.sheet")

    @app.post("/importar/forecast")
    def importar_forecast():
        arquivo = arquivo_xlsx()
        if not arquivo:
            return redirect(url_for("importar"))
        try:
            frentes, avisos = forecast.ler(arquivo.stream)
        except forecast.ErroForecast as erro:
            flash(str(erro), "erro")
            return redirect(url_for("importar"))
        subir.salvar_forecast(frentes, avisos, arquivo.filename)
        flash(f"Forecast importado: {len(frentes)} frentes.", "ok")
        return redirect(url_for("o_que_subir"))

    # ------------------------------------------------------------ O QUE SUBIR
    @app.get("/subir")
    def o_que_subir():
        janela = meses.janela()
        tudo = request.args.get("tudo") == "1"
        lista = subir.itens(janela)
        return render_template("subir.html", janela=janela, tudo=tudo,
                               itens=lista if tudo else [i for i in lista if i["muda"]],
                               total=len(lista), pendentes=sum(i["muda"] for i in lista),
                               sem_mas=subir.pendencias_de_para(), info=subir.info_forecast(),
                               lancamentos=subir.lancamentos())

    @app.post("/subir/lancar")
    def lancar():
        try:
            project_id = codigo("project_id")
            location_id = texto("location_id")
        except ValueError as erro:
            flash(str(erro), "erro")
            return redirect(url_for("o_que_subir"))
        feito = subir.lancar(project_id, location_id, meses.janela())
        if feito:
            flash(f"{feito}: lançamento registrado e controle atualizado.", "ok")
        else:
            flash("Nada para lançar nessa reserva (já está igual ao forecast).", "erro")
        return redirect(url_for("o_que_subir"))

    # ------------------------------------------------------------ FRENTES (de-para LOB -> MAS)
    @app.get("/frentes")
    def frentes():
        lista = banco.db().execute(
            """SELECT fr.*, (SELECT group_concat(DISTINCT f.endereco || ' ' || f.andar)
                             FROM forecast f WHERE f.lob = fr.lob) AS enderecos
               FROM frentes fr ORDER BY fr.project_id != '', fr.conta, fr.lob""").fetchall()
        return render_template("frentes.html", frentes=lista)

    @app.post("/frentes")
    def salvar_frente():
        try:
            lob = texto("lob")
            mas = request.form.get("project_id", "").strip().upper()
            if mas and not RE_CODIGO.match(mas):
                raise ValueError("MAS aceita só letras, números, - e _ (ex.: WHBRASIL006).")
            nome = texto("project_name", obrigatorio=False)
            cliente = texto("cliente", obrigatorio=False).upper()
        except ValueError as erro:
            flash(str(erro), "erro")
            return redirect(url_for("frentes"))
        con = banco.db()
        if not con.execute("UPDATE frentes SET project_id = ?, project_name = ?, cliente = ? "
                           "WHERE lob = ?", (mas, nome, cliente, lob)).rowcount:
            abort(404)
        banco.registrar("De-para alterado", f"{lob} → {mas or '(sem MAS)'}")
        con.commit()
        flash(f"Frente {lob} salva.", "ok")
        return redirect(url_for("frentes"))

    @app.post("/frentes/importar")
    def importar_de_para():
        arquivo = arquivo_xlsx()
        if not arquivo:
            return redirect(url_for("frentes"))
        try:
            achados = forecast.ler_de_para(arquivo.stream)
        except forecast.ErroForecast as erro:
            flash(str(erro), "erro")
            return redirect(url_for("frentes"))
        con = banco.db()
        preenchidas = 0
        for lob, dp in achados.items():
            # só preenche o que está vazio: não apaga o que você já digitou
            preenchidas += con.execute(
                """UPDATE frentes SET project_id = ?, cliente = CASE WHEN cliente = '' THEN ?
                   ELSE cliente END WHERE lob = ? AND project_id = ''""",
                (dp["project_id"], dp["cliente"].upper()[:LIMITE_TEXTO], lob)).rowcount
        banco.registrar("De-para importado", f"{preenchidas} frentes preenchidas")
        con.commit()
        flash(f"{preenchidas} frente(s) receberam o MAS do arquivo.", "ok")
        return redirect(url_for("frentes"))

    # ------------------------------------------------------------ HISTÓRICO
    @app.get("/historico")
    def historico():
        return render_template("historico.html", itens=banco.historico())


# ---------------------------------------------------------------- leitura de formulários

def arquivo_xlsx():
    """Confere o upload: tem que ser .xlsx de verdade. Se não for, avisa e devolve None."""
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename.lower().endswith(".xlsx"):
        flash("Escolha um arquivo .xlsx.", "erro")
        return None
    if arquivo.stream.read(2) != b"PK":                # todo .xlsx começa com "PK"
        flash("O arquivo não parece ser um Excel (.xlsx) válido.", "erro")
        return None
    arquivo.stream.seek(0)
    return arquivo


def ler_perfil():
    """Campos da aba Perfil, já validados, na ordem das colunas do banco."""
    status = texto("status")
    if status not in banco.STATUS:
        raise ValueError("Status inválido.")
    location_id = texto("location_id")
    if not banco.db().execute("SELECT 1 FROM locais WHERE location_id = ? AND ativo = 1",
                              (location_id,)).fetchone():
        raise ValueError("Escolha um local da lista.")
    return (texto("resv_desc").upper(), codigo("project_id"), texto("project_name"),
            texto("cliente", obrigatorio=False).upper(), location_id, status)


def ler_grade(janela):
    """
    Lê a grade de assentos. Cada linha i chega como:
      dept_code_i, dept_name_i, shift_i e q_i_AAAA-MM (um por mês).
    """
    total = int(request.form.get("linhas", 0))
    if total > 200:
        raise ValueError("Linhas demais na grade.")
    linhas, vistos = [], set()
    for i in range(total):
        dept = request.form.get(f"dept_code_{i}", "").strip().upper()
        if not dept:
            continue                                   # linha nova em branco
        shift = request.form.get(f"shift_{i}", "DED").strip().upper() or "DED"
        nome = request.form.get(f"dept_name_{i}", "").strip()[:LIMITE_TEXTO]
        if not RE_CODIGO.match(dept) or not RE_CODIGO.match(shift):
            raise ValueError(f"Dept Code/Shift inválido na linha {i + 1}: {dept} / {shift}")
        if (dept, shift) in vistos:
            raise ValueError(f"{dept} / {shift} aparece duas vezes.")
        vistos.add((dept, shift))
        qtd = {}
        for m in janela:
            bruto = request.form.get(f"q_{i}_{m.chave}", "").strip() or "0"
            if not bruto.isdigit() or int(bruto) > 100000:
                raise ValueError(f"Quantidade inválida em {dept} / {m.rotulo}: “{bruto}”.")
            qtd[m.chave] = int(bruto)
        linhas.append({"dept_code": dept, "dept_name": nome or planilhas.NOMES_DEPT.get(dept, ""),
                       "shift": shift, "qtd": qtd})
    return linhas


if __name__ == "__main__":
    # host 127.0.0.1 = só o seu PC acessa. debug=False = não expõe erros internos.
    porta = int(os.environ.get("CMAP_PORTA", "5000"))
    criar_app().run(host="127.0.0.1", port=porta, debug=False)
