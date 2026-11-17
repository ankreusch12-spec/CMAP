"""
Testes do forecast e do "O que subir". Dados 100% fictícios.
Rodar com:   python -m pytest
"""
import re
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import banco  # noqa: E402
import forecast  # noqa: E402
import meses  # noqa: E402
from app import criar_app  # noqa: E402

MES = meses.atual()
PROX = MES.somar(1)


def forecast_ficticio(caminho):
    """Monta uma aba BASE no formato do FORECAST OFICIAL com 3 frentes fictícias."""
    livro = Workbook()
    livro.active.title = "OBS"                       # aba qualquer antes da tabela
    aba = livro.create_sheet("Forecast Novo")        # nome diferente de BASE
    aba.append(["FORECAST OFICIAL - título em cima"])
    aba.append([])
    aba.append(["GERENCIA", "CODIGO / ACT ID", "CARGA", "CONTA", "SITE", "ACT ID/ INTEGRATION",
                "ACT ID / CARTEIRA", "ENDEREÇO INTEGRATION", "ANDAR", "Act ID", "LOB WFM", "DADO",
                MES.primeiro_dia, "W-45", PROX.primeiro_dia])

    def bloco(lob, end, andar, carga, mop, home_m, home_t, staff_ic, staff_ho, mop_prox=None):
        base = ["GER", "X", 1, "CLIENTE_Z", "CWB", "", "", end, andar, "W0TESTE", lob]
        for dado, v, v2 in [("PAS FIXAS", 999, 999), ("FATOR PA", 1, 1),
                            ("HOME MANHÃ", home_m, home_m), ("HOME TARDE", home_t, home_t),
                            (carga, 999, 999), ("STAFF HOME", staff_ho, staff_ho),
                            ("STAFF INCOMPANY", staff_ic, staff_ic),
                            ("MOP (ATIVO + AVISO PRÉVIO)", mop, mop if mop_prox is None else mop_prox)]:
            aba.append(base + [dado, v, 123, v2])

    bloco("FRENTE MEIO PERIODO", "Curitiba Marechal 3", "1ª", "6H20", 27, 0, 0, 0, 0, mop_prox=30)
    bloco("FRENTE INTEGRAL", "Curitiba Marechal 3", "2ª", "7H12", 10, 2, 1, 2, 1)
    bloco("FRENTE FORTALEZA", "Fortaleza Gonçalves Ledo", "1ª", "7H12", 50, 0, 0, 0, 0)
    aba.append(["-"] * 12)
    livro.save(caminho)


@pytest.fixture
def app(tmp_path):
    return criar_app({"TESTING": True, "BANCO": str(tmp_path / "t.db"), "USUARIO": "Teste"})


@pytest.fixture
def cliente(app):
    c = app.test_client()
    html = c.get("/importar").get_data(as_text=True)
    c.token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    return c


def test_regras_do_calculo(tmp_path):
    caminho = tmp_path / "f.xlsx"
    forecast_ficticio(caminho)
    frentes, avisos = forecast.ler(caminho)
    assert len(frentes) == 3
    assert any("FATOR PA" in a for a in avisos)          # 6H20 com FATOR PA 1 no arquivo
    de_para = {"FRENTE MEIO PERIODO": {"project_id": "EXEMPLO100", "cliente": "Z"},
               "FRENTE INTEGRAL": {"project_id": "EXEMPLO100", "cliente": "Z"},
               "FRENTE FORTALEZA": {"project_id": "EXEMPLO200", "cliente": "Z"}}
    meus = {"BR-CUR-MALDE-02", "BR-WFH-DIRETO"}
    r = forecast.calcular(frentes, de_para, meses.janela(), lambda l: l in meus)

    predio = r[("EXEMPLO100", "BR-CUR-MALDE-02")]
    # 27 ÷ 2 = 13,5  +  (10 − 3 home) ÷ 1 = 7   ->  20,5  ->  arredonda para cima = 21
    assert predio["agentes"][MES.chave] == 21
    # próximo mês: 30 ÷ 2 = 15 + 7 = 22
    assert predio["agentes"][PROX.chave] == 22
    assert predio["staff"][MES.chave] == 2                 # STAFF INCOMPANY
    home = r[("EXEMPLO100", "BR-WFH-DIRETO")]
    assert home["agentes"][MES.chave] == 3                 # HOME MANHÃ + TARDE
    assert home["staff"][MES.chave] == 1                   # STAFF HOME
    assert ("EXEMPLO200", "BR-CEA-LEDOS") not in r         # Fortaleza: não acompanho
    assert forecast.resv_desc({"cliente": "Cliente Z", "project_id": "X"}, "BR-CUR-MALDE-02") == "CLIENTE_Z_MAL3"


def test_fluxo_o_que_subir(cliente, app, tmp_path):
    t = cliente.token
    with app.app_context():                                # locais acompanhados
        con = banco.db()
        for loc in ("BR-CUR-MALDE-02", "BR-WFH-DIRETO"):
            con.execute("INSERT INTO locais (location_id, descricao) VALUES (?, ?)", (loc, loc))
        con.commit()

    caminho = tmp_path / "f.xlsx"
    forecast_ficticio(caminho)
    with caminho.open("rb") as f:
        r = cliente.post("/importar/forecast", data={"csrf_token": t, "arquivo": (f, "f.xlsx")},
                         content_type="multipart/form-data")
    assert r.headers["Location"].endswith("/subir")

    # sem MAS ainda: aparece o alerta
    assert "sem MAS" in cliente.get("/subir").get_data(as_text=True)

    # de-para pelo "controle antigo" (aba com LOB WFM e MAS)
    antigo = tmp_path / "antigo.xlsx"
    livro = Workbook()
    livro.active.append(["GERENCIA", "CONTA", "ENDEREÇO", "MAS", "LOB WFM", "DADO"])
    livro.active.append(["G", "CLIENTE_Z", "x", "EXEMPLO100", "FRENTE MEIO PERIODO", "MOP"])
    livro.active.append(["G", "CLIENTE_Z", "x", "=ruim", "FRENTE INTEGRAL", "MOP"])  # MAS inválido
    livro.save(antigo)
    with antigo.open("rb") as f:
        cliente.post("/frentes/importar", data={"csrf_token": t, "arquivo": (f, "antigo.xlsx")},
                     content_type="multipart/form-data")
    # a outra frente o usuário preenche na mão
    cliente.post("/frentes", data={"csrf_token": t, "lob": "FRENTE INTEGRAL",
                                   "project_id": "exemplo100", "project_name": "P_Z", "cliente": "z"})

    html = cliente.get("/subir").get_data(as_text=True)
    assert "CLIENTE_Z_MAL3" in html and "nova no CMAP" in html

    # lança o prédio
    cliente.post("/subir/lancar", data={"csrf_token": t, "project_id": "EXEMPLO100",
                                        "location_id": "BR-CUR-MALDE-02"})
    with app.app_context():
        res = banco.reservas()
        assert [r["resv_desc"] for r in res] == ["CLIENTE_Z_MAL3"]
        grade = {l["dept_code"]: l["qtd"] for l in banco.grade_assentos(res[0]["id"], meses.janela())}
        assert grade["PRODUCAGENT-DIR"][MES.chave] == 21
        assert grade["TEAMLEADER-DIR"][MES.chave] == 2
        assert banco.db().execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 1

    # lançar de novo não muda nada
    r = cliente.post("/subir/lancar", data={"csrf_token": t, "project_id": "EXEMPLO100",
                                            "location_id": "BR-CUR-MALDE-02"}, follow_redirects=True)
    assert "Nada para lançar" in r.get_data(as_text=True)


def test_forecast_sem_aba_base(cliente, tmp_path):
    caminho = tmp_path / "x.xlsx"
    Workbook().save(caminho)
    with caminho.open("rb") as f:
        r = cliente.post("/importar/forecast", data={"csrf_token": cliente.token, "arquivo": (f, "x.xlsx")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "Não encontrei o forecast" in r.get_data(as_text=True)


def test_visao_por_gestor(cliente, app, tmp_path):
    t = cliente.token
    with app.app_context():
        con = banco.db()
        for loc in ("BR-CUR-MALDE-02", "BR-WFH-DIRETO"):
            con.execute("INSERT INTO locais (location_id, descricao) VALUES (?, ?)", (loc, loc))
        con.commit()
    caminho = tmp_path / "f.xlsx"
    forecast_ficticio(caminho)
    with caminho.open("rb") as f:
        cliente.post("/importar/forecast", data={"csrf_token": t, "arquivo": (f, "f.xlsx")},
                     content_type="multipart/form-data")
    for lob in ("FRENTE MEIO PERIODO", "FRENTE INTEGRAL"):
        cliente.post("/frentes", data={"csrf_token": t, "lob": lob, "project_id": "EXEMPLO100",
                                       "project_name": "P_Z", "cliente": "Z"})
    # reserva no CMAP com 20 agentes e 2 staff -> 21 ocupadas / 20 = 105%
    cliente.post("/subir/lancar", data={"csrf_token": t, "project_id": "EXEMPLO100",
                                        "location_id": "BR-CUR-MALDE-02"})
    with app.app_context():
        import gestores
        bloco = gestores.visao(MES)[0]
        assert bloco["gerente"] == "GER"
        col = next(c for c in bloco["colunas"] if c["location_id"] == "BR-CUR-MALDE-02")
        assert col["site"] == "M3 - 1º, 2º"
        assert (col["hc"], col["home"]) == (37, 3)            # MOP 27 + 10; home 3
        assert (col["ag_ocup"], col["ag_disp"]) == (21, 21)   # já lançado: 100%
        assert col["staff_do_forecast"] and col["st_ocup"] == 2
        assert gestores.faixa(col["ag_pct"]) == "ok"
        assert gestores.andar_curto("TORRE A - 2ª") == "Torre A - 2º"

    # detalhe digitado substitui o staff do forecast
    cliente.post("/gestores/detalhe", data={"csrf_token": t, "project_id": "EXEMPLO100",
                                            "location_id": "BR-CUR-MALDE-02",
                                            "particularidades": "Ambientação", "supervisores": "3",
                                            "plan_wfm": "1", "qualidade": "", "gerentes": "0"})
    html = cliente.get(f"/gestores?mes={MES.chave}").get_data(as_text=True)
    assert "OPERAÇÕES GER" in html and "Ambientação" in html
    with app.app_context():
        col = next(c for c in gestores.visao(MES)[0]["colunas"] if c["location_id"] == "BR-CUR-MALDE-02")
        assert col["st_ocup"] == 4 and not col["staff_do_forecast"]
    # número inválido é recusado
    r = cliente.post("/gestores/detalhe", data={"csrf_token": t, "project_id": "EXEMPLO100",
                                                "location_id": "BR-CUR-MALDE-02", "supervisores": "-1"},
                     follow_redirects=True)
    assert "número inválido" in r.get_data(as_text=True)


def test_maior_turno_nas_frentes_6h20():
    seis = {"fator": 2}
    # exemplo do quadro (CRF 3): 60 HCs, 45 manhã, 15 tarde -> 45 PAs
    assert forecast.pas_no_predio(seis, {"mop": 60, "home": 0, "ic_manha": 45, "ic_tarde": 15}) == 45
    # MOP menor que o planejado: reparte na proporção (77 × 46 ÷ 87 = 40,7)
    assert round(forecast.pas_no_predio(seis, {"mop": 92, "home": 15, "ic_manha": 46,
                                               "ic_tarde": 41}), 1) == 40.7
    # sem manhã/tarde no arquivo: ÷ 2
    assert forecast.pas_no_predio(seis, {"mop": 27, "home": 0}) == 13.5
    # integral: MOP − Home
    assert forecast.pas_no_predio({"fator": 1}, {"mop": 10, "home": 3, "ic_manha": 9}) == 7


def test_forecast_ligado_ao_arquivo(tmp_path):
    import os
    pasta = tmp_path / "Forecast"
    pasta.mkdir()
    forecast_ficticio(pasta / "FORECAST OFICIAL.xlsx")
    Workbook().save(pasta / "outra planilha.xlsx")      # mais nova, mas não é forecast
    (tmp_path / "caminhos.txt").write_text(f"# comentário\nforecast = \"{pasta}\"\n", encoding="utf-8")
    assert forecast.ler_caminhos(tmp_path / "caminhos.txt")["forecast"] == str(pasta)

    app = criar_app({"TESTING": True, "BANCO": str(tmp_path / "t.db"), "FORECAST_CAMINHO": str(pasta)})
    c = app.test_client()

    def importacoes():
        with app.app_context():
            return banco.db().execute(
                "SELECT COUNT(*) FROM historico WHERE acao = 'Forecast importado'").fetchone()[0]

    assert "Forecast atualizado sozinho" in c.get("/subir").get_data(as_text=True)
    assert importacoes() == 1
    c.get("/gestores")                                    # nada mudou: não lê de novo
    assert importacoes() == 1
    arq = pasta / "FORECAST OFICIAL.xlsx"
    os.utime(arq, (arq.stat().st_atime, arq.stat().st_mtime + 60))   # arquivo salvo de novo
    c.get("/frentes")
    assert importacoes() == 2

    # caminho errado: avisa e mantém o último forecast
    app.config["FORECAST_CAMINHO"] = str(tmp_path / "nao existe")
    html = c.get("/subir").get_data(as_text=True)
    assert "Não achei o forecast" in html and "FORECAST OFICIAL.xlsx" in html


def test_configurar_cria_caminhos(tmp_path, monkeypatch):
    import configurar
    pasta = tmp_path / "Forecast"
    pasta.mkdir()
    forecast_ficticio(pasta / "FORECAST.xlsx")
    monkeypatch.setattr(configurar, "ARQUIVO", tmp_path / "caminhos.txt")
    respostas = iter(["Fulana de Tal", str(tmp_path / "errado"), f'"{pasta}"'])  # 1º caminho errado
    monkeypatch.setattr("builtins.input", lambda _msg="": next(respostas))
    configurar.main()
    lido = forecast.ler_caminhos(tmp_path / "caminhos.txt")
    assert lido == {"usuario": "Fulana de Tal", "forecast": str(pasta)}
