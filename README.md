# CMAP — Controle de lugares

Página web **local** para organizar as reservas de assentos no **mesmo padrão do CMAP** (Archibus):
os mesmos campos, os mesmos códigos de local e a mesma grade de 12 meses. Assim, o que está no
controle bate com o que é lançado no CMAP e com a planilha da reunião de segunda.

**Locais acompanhados:** São Paulo (BF4 Tagipuru e Barueri), Curitiba (JL1, JL2, JL3, Marechal 2 e
Marechal 3) e Ponta Grossa. Os demais locais do CMAP (Fortaleza, EZ Tower...) são ignorados no painel,
nas reservas e na importação. A lista fica em `banco.py` (`MEUS_LOCAIS`) e pode ser ajustada na tela
**Locais**, na coluna “Acompanho”.

> 🔒 **Os dados ficam só no seu PC.** Este repositório guarda apenas o **código**.
> Planilhas, exports e o banco de dados são bloqueados pelo `.gitignore`. Veja [SEGURANCA.md](SEGURANCA.md).

---

## O que tem em cada tela

| Tela | Para que serve | No CMAP equivale a |
|---|---|---|
| **O que subir** | Forecast × o que está no CMAP, por reserva (MAS + local) e mês: ▲ aumentar, ▼ reduzir, reservas novas. Botão **✔ Lançado no CMAP** atualiza o controle e registra o lançamento. | — |
| **Frentes** | De-para LOB WFM → MAS (Project ID), preenchido uma vez (pode vir do controle antigo). | — |
| **Painel** | Ocupação por cidade e local, mês a mês: Res, Avai, % (mesma conta da planilha), com subtotal por cidade. Negativo em vermelho. | Aba *Summary* da planilha |
| **Ver reserva** | Lista de reservas com filtro em cada coluna, “Cópia” e “Mostrar tudo”. | *Ver reserva* |
| **Reserva → Perfil** | Resv. Desc., ID/nome do projeto, cliente, local e status. | aba *Perfil* |
| **Reserva → Assentos** | Grade Dept Code × mês (Nov-2026 … Oct-2027). Mês atual e próximo em rosa. | aba *Assentos* |
| **Locais** | De-para Location ID ↔ Site ID ↔ descrição, e a capacidade de cada local. | *Disponibilidade de locais* |
| **Importar** | Lê o relatório exportado do CMAP (mesmas colunas da aba *12 month forecast*). | — |
| **Exportar Excel** | Gera Excel com 3 abas: Reservas, Assentos (grade) e Relatório CMAP. | — |
| **Histórico** | Quem criou/alterou/importou o quê, e quando. | — |

---

## Como rodar no seu PC (passo a passo)

**1. Ter o Python instalado** (3.11 ou mais novo). No Windows, confira no Prompt de Comando:

```bash
py --version
```

Se não tiver, peça ao TI (em PC da empresa geralmente é pelo portal de software).

**2. Baixar o projeto** (no GitHub: botão *Code → Download ZIP*, ou com git):

```bash
git clone https://github.com/ankreusch12-spec/CMAP.git
```

**3. Entrar na pasta e criar o ambiente** (só na primeira vez):

```bash
cd CMAP
```

```bash
py -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

**4. (Opcional) Carregar dados de exemplo** para conhecer as telas:

```bash
python dados_exemplo.py
```

**5. Abrir o controle:**

```bash
python app.py
```

E abra no navegador: **http://127.0.0.1:5000**. Para parar, `Ctrl + C` no terminal.

> Nas próximas vezes, basta: abrir o terminal na pasta, `.venv\Scripts\activate` e `python app.py`.

**Seu nome no histórico:** antes do `python app.py`, rode `set CMAP_USUARIO=Seu Nome` (Windows).

---

## Regras do cálculo (forecast → CMAP)

Do **FORECAST OFICIAL** (aba `BASE`) usamos, por frente e mês: a carga (**6H20** ou **7H12**), o **MOP**,
Home manhã/tarde e Staff incompany/home.

| O quê | Regra |
|---|---|
| PAs no prédio (PRODUCAGENT-DIR) | (MOP − Home) ÷ **2** nas frentes 6H20; ÷ **1** nas integrais (7H12) |
| Home office | reserva separada em *WAH Brasil Direto WFH* (`_HO`) com o Home |
| Staff (TEAMLEADER-DIR) | Staff incompany no prédio; Staff home na reserva `_HO` |
| Arredondamento | **sempre para cima**, depois de somar tudo do mesmo MAS + local |

O endereço do forecast vira o Location ID do CMAP pelo nome (ex.: “Curitiba Marechal 3” → `BR-CUR-MALDE-02`;
andar “HOME OFFICE” → `BR-WFH-DIRETO`). Avisos da importação mostram frentes sem 6H20/7H12, FATOR PA do
arquivo diferente da regra e endereços não reconhecidos.

## Rotina sugerida

1. **Importar** o forecast novo (e, se quiser conferir, o relatório do CMAP).
2. **O que subir**: para cada reserva com ▲/▼, lance no CMAP e clique **✔ Lançado no CMAP**.
3. Frentes novas sem MAS aparecem em alerta → preencha em **Frentes**.

## Conferência com a planilha de capacidade (reunião de segunda)

1. No CMAP, exporte o relatório de reservas (o mesmo da aba *12 month forecast*).
2. No controle: **Importar** → escolha o arquivo.
3. **Painel**: confira locais acima da capacidade (vermelho) e as diferenças com a planilha.
4. Ajuste as reservas (Perfil / Assentos) com o que for decidido na reunião.
5. **Exportar Excel** → use a aba *Assentos* para lançar no CMAP, no mesmo formato da tela.

---

## Como o código está organizado

```
app.py            as páginas (rotas) — comece por aqui
banco.py          banco de dados SQLite e consultas
planilhas.py      importar / exportar Excel no formato do CMAP
meses.py          janela de 12 meses (Nov-2026 ... Oct-2027)
seguranca.py      proteções (CSRF, só acesso local, cabeçalhos)
dados_exemplo.py  dados fictícios para teste
templates/        HTML de cada tela
static/           estilo (CSS) e JavaScript
tests/            testes automáticos  ->  python -m pytest
```
