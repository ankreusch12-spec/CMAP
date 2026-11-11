# CMAP — Controle de lugares

Página web **local** para organizar as reservas de assentos no **mesmo padrão do CMAP** (Archibus):
os mesmos campos, os mesmos códigos de local e a mesma grade de 12 meses. Assim, o que está no
controle bate com o que é lançado no CMAP e com a planilha da reunião de segunda.

> 🔒 **Os dados ficam só no seu PC.** Este repositório guarda apenas o **código**.
> Planilhas, exports e o banco de dados são bloqueados pelo `.gitignore`. Veja [SEGURANCA.md](SEGURANCA.md).

---

## O que tem em cada tela

| Tela | Para que serve | No CMAP equivale a |
|---|---|---|
| **Painel** | Ocupação por local e mês: Res, Avai, % (mesma conta da planilha). Negativo em vermelho. | Aba *Summary* da planilha |
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

## Rotina sugerida (reunião de segunda)

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
