"""
Testes automáticos. Rodar com:   python -m pytest
Usam um banco temporário e dados fictícios — nada do seu banco real é tocado.
"""
import re
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import banco  # noqa: E402
import meses  # noqa: E402
from app import criar_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return criar_app({"TESTING": True, "BANCO": str(tmp_path / "teste.db"), "USUARIO": "Teste"})


@pytest.fixture
def cliente(app):
    return app.test_client()


def token(cliente, url="/locais"):
    html = cliente.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def relatorio_cmap(caminho, linhas):
    """Cria um xlsx no formato do relatório do CMAP (cabeçalho na linha 3)."""
    livro = Workbook()
    aba = livro.active
    aba.append(["Relatório de teste"])
    aba.append([])
    aba.append(["Geo", "Region", "Country", "Location ID", "Site ID", "Site", "Client",
                "Project ID", "Project", "Dept", "Shift", "Type", "Eff Date", "Qty"])
    for l in linhas:
        aba.append(l)
    livro.save(caminho)


def test_meses():
    m = meses.Mes(2026, 11)
    assert m.rotulo == "Nov-2026"
    assert m.somar(2) == meses.Mes(2027, 1)
    assert meses.de_valor("11/1/2026") == m
    assert meses.de_valor("Nov-2026") == m
    assert len(meses.janela(m)) == 12


def test_post_sem_csrf_e_recusado(cliente):
    r = cliente.post("/locais", data={"location_id": "BR-X", "descricao": "X"})
    assert r.status_code == 400


def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"


def test_fluxo_completo(cliente, app, tmp_path):
    t = token(cliente)
    # cria local
    cliente.post("/locais", data={"csrf_token": t, "location_id": "br-pon-ruase",
                                  "site_id": "bpg", "descricao": "Ponta Grossa",
                                  "capacidade": "30"})
    # cria reserva
    r = cliente.post("/reservas/nova", data={
        "csrf_token": t, "resv_desc": "cliente_a_pg", "project_id": "EXEMPLO001",
        "project_name": "P_CLIENTE_A", "cliente": "cliente_a",
        "location_id": "BR-PON-RUASE", "status": "Confirmado"})
    rid = int(re.search(r"/reservas/(\d+)", r.headers["Location"]).group(1))

    # preenche assentos: 25 agentes + 10 líderes = 35 > 30 de capacidade
    janela = meses.janela()
    dados = {"csrf_token": t, "linhas": "2",
             "dept_code_0": "PRODUCAGENT-DIR", "shift_0": "DED",
             "dept_code_1": "teamleader-dir", "shift_1": "DED"}
    for m in janela:
        dados[f"q_0_{m.chave}"] = "25"
        dados[f"q_1_{m.chave}"] = "10"
    assert cliente.post(f"/reservas/{rid}/assentos", data=dados).status_code == 302

    with app.app_context():
        linhas, totais = banco.ocupacao(janela)
        cel = linhas[0]["celulas"][0]
        assert (cel["res"], cel["disp"]) == (35, -5)
        assert banco.grade_assentos(rid, janela)[1]["dept_name"] == "COGS (SITE) Team Leader Direct"

    # painel mostra o negativo em vermelho
    assert 'class="num negativo"' in cliente.get("/").get_data(as_text=True)

    # quantidade inválida é recusada
    dados[f"q_0_{janela[0].chave}"] = "-3"
    cliente.post(f"/reservas/{rid}/assentos", data=dados)
    with app.app_context():
        assert banco.grade_assentos(rid, janela)[0]["qtd"][janela[0].chave] == 25

    # cópia
    cliente.post(f"/reservas/{rid}/copia", data={"csrf_token": t})
    with app.app_context():
        assert len(banco.reservas()) == 2

    # exportar -> reimportar não duplica
    xlsx = cliente.get("/exportar").data
    caminho = tmp_path / "export.xlsx"
    caminho.write_bytes(xlsx)
    assert load_workbook(caminho).sheetnames == ["Reservas", "Assentos", "Relatorio CMAP"]
    with caminho.open("rb") as f:
        cliente.post("/importar", data={"csrf_token": t, "arquivo": (f, "export.xlsx")},
                     content_type="multipart/form-data")
    with app.app_context():
        assert len(banco.reservas()) == 2


def test_importar_relatorio_cmap(cliente, app, tmp_path):
    t = token(cliente, "/importar")
    caminho = tmp_path / "cmap.xlsx"
    inicio = meses.atual().primeiro_dia
    relatorio_cmap(caminho, [
        ["LATAM", "Brazil", "Brazil", "BR-BAR-ARAGU", "BAA", "Barueri Araguaia", "CLIENTE_X",
         "EXEMPLO009", "Projeto X", "PRODUCAGENT-DIR", "DED", "A", inicio, 7],
        ["LATAM", "Brazil", "Brazil", "BR-BAR-ARAGU", "BAA", "Barueri Araguaia", "CLIENTE_X",
         "EXEMPLO009", "Projeto X", "PRODUCAGENT-DIR", "DED", "A", inicio, 3],   # soma: 10
        ["LATAM", "Mexico", "Mexico", "MX-XXX", "MXA", "Outro país", "CLIENTE_Y",
         "EXEMPLO010", "Projeto Y", "PRODUCAGENT-DIR", "DED", "A", inicio, 99],  # ignorado
        ["=cmd", "Brazil", "Brazil", "BR-BAR-ARAGU", "BAA", "Barueri Araguaia", "CLIENTE_X",
         "EXEMPLO009", "Projeto X", "TEAMLEADER-DIR", "DED", "A", "data ruim", 1],  # aviso
    ])
    with caminho.open("rb") as f:
        cliente.post("/importar", data={"csrf_token": t, "arquivo": (f, "cmap.xlsx")},
                     content_type="multipart/form-data")
    with app.app_context():
        res = banco.reservas()
        assert len(res) == 1 and res[0]["resv_desc"] == "CLIENTE_X_BAA"
        grade = banco.grade_assentos(res[0]["id"], meses.janela())
        assert grade[0]["qtd"][meses.atual().chave] == 10


def test_upload_que_nao_e_excel(cliente, tmp_path):
    t = token(cliente, "/importar")
    falso = tmp_path / "falso.xlsx"
    falso.write_text("isto não é excel")
    with falso.open("rb") as f:
        r = cliente.post("/importar", data={"csrf_token": t, "arquivo": (f, "falso.xlsx")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "não parece ser um Excel" in r.get_data(as_text=True)


def test_exportar_neutraliza_formulas(cliente, app, tmp_path):
    t = token(cliente)
    cliente.post("/locais", data={"csrf_token": t, "location_id": "BR-A", "descricao": "A"})
    cliente.post("/reservas/nova", data={
        "csrf_token": t, "resv_desc": "X", "project_id": "P1",
        "project_name": "=HYPERLINK(\"http://exemplo\")", "location_id": "BR-A",
        "status": "Confirmado"})
    caminho = tmp_path / "e.xlsx"
    caminho.write_bytes(cliente.get("/exportar").data)
    valor = load_workbook(caminho)["Reservas"]["C2"].value
    assert valor.startswith("'=")
