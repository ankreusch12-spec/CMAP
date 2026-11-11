"""
dados_exemplo.py — carrega dados FICTÍCIOS para testar o controle.

    python dados_exemplo.py

- Os locais seguem o de-para do CMAP (Location ID / descrição). Só os de
  banco.MEUS_LOCAIS ficam marcados como "Acompanho".
- Capacidades, projetos e clientes são INVENTADOS (CLIENTE_A, EXEMPLO001...).
  Os dados reais entram pela tela "Importar" e ficam só no seu PC.
"""
from datetime import date

import banco
import forecast
import meses
import subir
from app import criar_app

# (Location ID, Site ID, Descrição, capacidade fictícia)
LOCAIS = [
    ("BR-BAR-ARAGU", "BAA", "Barueri Araguaia", 300),
    ("BR-CEA-LEDOS", "", "Fortaleza Gonçalves Ledo", 1200),
    ("BR-CUR-BARAO", "", "Curitiba Barão", 0),
    ("BR-CUR-JOSEL-01", "CJ1", "Curitiba José Loureiro 1", 700),
    ("BR-CUR-JOSEL-02", "CJ2", "Curitiba José Loureiro 2", 1400),
    ("BR-CUR-JOSEL-03", "", "Curitiba José Loureiro 3", 400),
    ("BR-CUR-MALDE-01", "CM2", "Curitiba Marechal 2", 900),
    ("BR-CUR-MALDE-02", "", "Curitiba Marechal 3", 750),
    ("BR-CUR-MALDE-03", "", "Curitiba Tibagi", 0),
    ("BR-CUR-MURIC", "", "Curitiba Muricy", 850),
    ("BR-PON-RUASE", "BPG", "Ponta Grossa", 780),
    ("BR-SAO-EZTOW", "", "Torre EZ de São Paulo", 650),
    ("BR-SÃO-FRANÇA", "", "São Paulo Água Branca", 450),
    ("BR-SAO-TAGIP", "", "São Paulo Barra Funda BF4 Tagipuru", 2000),
    ("BR-WFH-DIRETO", "BWD", "WAH Brasil Direto WFH", 0),
    ("BR-WFH-INDIR", "", "Trabalho Remoto - Indireto", 0),
]

# (Resv. Desc., Project ID, Projeto, Cliente, Location ID, Status, agentes, líderes)
RESERVAS = [
    ("CLIENTE_A_PG", "EXEMPLO001", "P_CLIENTE_A COBRANCA_CWB", "CLIENTE_A", "BR-PON-RUASE", "Confirmado", 25, 1),
    ("CLIENTE_B_MAL2", "EXEMPLO002", "P_CLIENTE_B_CWB", "CLIENTE_B", "BR-CUR-MALDE-01", "Confirmado", 120, 6),
    ("CLIENTE_C_MAL2", "EXEMPLO003", "P_CLIENTE_C_CWB", "CLIENTE_C", "BR-CUR-MALDE-01", "Confirmado", 60, 3),
    ("CLIENTE_D_BAR", "EXEMPLO004", "P_CLIENTE_D_SP", "CLIENTE_D", "BR-BAR-ARAGU", "Fila mensal", 40, 2),
    ("CLIENTE_E_JL1", "EXEMPLO004", "P_CLIENTE_D_CWB", "CLIENTE_D", "BR-CUR-JOSEL-01", "Confirmado", 300, 15),
    ("CLIENTE_F_JL2", "EXEMPLO005", "P_CLIENTE_F_CWB", "CLIENTE_F", "BR-CUR-JOSEL-02", "Confirmado", 1340, 60),
    ("CLIENTE_G_BF4", "EXEMPLO006", "P_CLIENTE_G_SP", "CLIENTE_G", "BR-SAO-TAGIP", "Confirmado", 900, 45),
    ("CLIENTE_H_MAL3", "EXEMPLO007", "P_CLIENTE_H_CWB", "CLIENTE_H", "BR-CUR-MALDE-02", "Rascunho", 30, 2),
    ("CLIENTE_I_JL3", "EXEMPLO008", "P_CLIENTE_I_CWB", "CLIENTE_I", "BR-CUR-JOSEL-03", "Confirmado", 150, 8),
]


# Forecast fictício: (LOB, conta, endereço, andar, carga, MOP, home, staff, MAS, crescimento/mês)
FORECAST = [
    ("LOB EXEMPLO A", "CLIENTE_A", "Ponta Grossa Brazil-Rua Sete de Setembro", "3ª", "7H12", 27, 0, 1, "EXEMPLO001", 0),
    ("LOB EXEMPLO B", "CLIENTE_B", "Curitiba Marechal 2", "3ª", "6H20", 260, 20, 6, "EXEMPLO002", 0),
    ("LOB EXEMPLO F", "CLIENTE_F", "Curitiba Jose Loureiro 2", "3ª", "7H12", 1300, 0, 60, "EXEMPLO005", 4),
    ("LOB EXEMPLO J", "CLIENTE_J", "Curitiba Jose Loureiro 1", "1ª", "6H20", 81, 0, 3, "EXEMPLO009", 0),
    ("LOB SEM MAS", "CLIENTE_K", "Sao Paulo - Rua Tagipuru", "TORRE A - 2ª", "7H12", 40, 0, 2, "", 0),
]


def carregar_forecast(janela):
    frentes = []
    for lob, conta, end, andar, carga, mop, home, staff, mas, cresce in FORECAST:
        frentes.append({
            "lob": lob, "act_id": "W0EXEMP", "conta": conta, "endereco": end, "andar": andar,
            "location_id": forecast.local_do_endereco(end, andar),
            "carga": carga, "fator": 2 if carga == "6H20" else 1,
            "valores": {m.chave: {"mop": mop + cresce * i, "home": home, "staff_ic": staff,
                                  "staff_ho": 0} for i, m in enumerate(janela)}})
    subir.salvar_forecast(frentes, ["Exemplo de aviso: FATOR PA diferente da regra."],
                          "FORECAST_EXEMPLO.xlsx")
    con = banco.db()
    for lob, conta, *_, mas, _c in FORECAST:
        con.execute("UPDATE frentes SET project_id = ?, cliente = ? WHERE lob = ?", (mas, conta, lob))
    con.commit()


def carregar():
    app = criar_app()
    with app.app_context():
        con = banco.db()
        con.executemany("""INSERT OR IGNORE INTO locais
                           (location_id, site_id, descricao, capacidade, ativo)
                           VALUES (?, ?, ?, ?, ?)""",
                        [(*l, int(l[0] in banco.MEUS_LOCAIS)) for l in LOCAIS])
        janela = meses.janela()
        for desc, pid, nome, cli, loc, status, agentes, lideres in RESERVAS:
            if con.execute("SELECT 1 FROM reservas WHERE resv_desc = ?", (desc,)).fetchone():
                continue
            cur = con.execute(
                """INSERT INTO reservas (resv_desc, project_id, project_name, cliente,
                       location_id, status, criado_em, criado_por)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'Usuário Exemplo')""",
                (desc, pid, nome, cli, loc, status, date.today().isoformat()))
            for i, m in enumerate(janela):
                extra = 5 if i >= 2 and agentes > 100 else 0   # cresce a partir do 3º mês
                for dept, nome_dept, qtd in (
                        ("PRODUCAGENT-DIR", "COGS (SITE) Production Agent Direct", agentes + extra),
                        ("TEAMLEADER-DIR", "COGS (SITE) Team Leader Direct", lideres)):
                    con.execute("""INSERT INTO assentos (reserva_id, dept_code, dept_name, shift, mes, qtd)
                                   VALUES (?, ?, ?, 'DED', ?, ?)""",
                                (cur.lastrowid, dept, nome_dept, m.chave, qtd))
        carregar_forecast(janela)
        banco.registrar("Dados de exemplo carregados", "", con)
        con.commit()
    print("Dados de exemplo carregados. Rode: python app.py")


if __name__ == "__main__":
    carregar()
