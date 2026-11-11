"""
dados_exemplo.py — carrega dados FICTÍCIOS para testar o controle.

    python dados_exemplo.py

- Os locais seguem o de-para do CMAP (Location ID / descrição).
- Capacidades, projetos e clientes são INVENTADOS (CLIENTE_A, EXEMPLO001...).
  Os dados reais entram pela tela "Importar" e ficam só no seu PC.
"""
from datetime import date

import banco
import meses
from app import criar_app

# (Location ID, Site ID, Descrição, capacidade fictícia)
LOCAIS = [
    ("BR-BAR-ARAGU", "BAA", "Barueri Araguaia", 300),
    ("BR-CEA-LEDOS", "", "Fortaleza Gonçalves Ledo", 1200),
    ("BR-CUR-BARAO", "", "Curitiba Barão", 0),
    ("BR-CUR-JOSEL-01", "CJ1", "Curitiba José Loureiro 1", 700),
    ("BR-CUR-JOSEL-02", "CJ2", "Curitiba José Loureiro 2", 1400),
    ("BR-CUR-JOSEL-03", "", "Curitiba José Loureiro 3", 0),
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
    ("CLIENTE_D_HO", "EXEMPLO004", "P_CLIENTE_D_CWB", "CLIENTE_D", "BR-WFH-DIRETO", "Fila mensal", 40, 2),
    ("CLIENTE_E_JL1", "EXEMPLO004", "P_CLIENTE_D_CWB", "CLIENTE_D", "BR-CUR-JOSEL-01", "Confirmado", 300, 15),
    ("CLIENTE_F_JL2", "EXEMPLO005", "P_CLIENTE_F_CWB", "CLIENTE_F", "BR-CUR-JOSEL-02", "Confirmado", 1340, 60),
    ("CLIENTE_G_EZ", "EXEMPLO006", "P_CLIENTE_G_SP", "CLIENTE_G", "BR-SAO-EZTOW", "Rascunho", 30, 2),
]


def carregar():
    app = criar_app()
    with app.app_context():
        con = banco.db()
        con.executemany("""INSERT OR IGNORE INTO locais (location_id, site_id, descricao, capacidade)
                           VALUES (?, ?, ?, ?)""", LOCAIS)
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
        banco.registrar("Dados de exemplo carregados", "", con)
        con.commit()
    print("Dados de exemplo carregados. Rode: python app.py")


if __name__ == "__main__":
    carregar()
