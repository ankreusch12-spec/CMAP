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
| **Gestores** | “Resumo CMAP - Ocupação prédios” por gestor (GERENCIA do forecast): uma coluna por conta/prédio com HCs, PA's ocupadas × reservadas, staff e % de ocupação; particularidades e staff detalhado editáveis. | — |
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

## Como instalar e usar no seu PC (passo a passo)

São **4 passos na primeira vez**. Depois, só o passo 4.

**1. Python instalado** (3.11 ou mais novo). Se não tiver, peça ao TI / Portal da Empresa e, na
instalação, marque **“Add python.exe to PATH”**.

**2. Baixar o controle**
- Abra o link (logado no GitHub):
  https://github.com/ankreusch12-spec/CMAP/archive/refs/heads/claude/gallant-wright-stczq4.zip
  (depois que o código for para o `main`: botão verde **Code → Download ZIP** na página do repositório).
- Clique com o botão direito no ZIP → **Extrair tudo…** → escolha uma pasta fixa, por exemplo
  `Documentos\Controle CMAP`. Não rode de dentro do ZIP.

**3. Instalar** — dê **dois cliques em `instalar.bat`**. Ele:
- confere o Python;
- cria o ambiente do controle (pasta `.venv`) e instala as bibliotecas;
- pergunta **seu nome** (aparece no Histórico) e o **caminho do forecast**
  (no Explorador: Shift + botão direito no arquivo ou na pasta → *Copiar como caminho* → cole com Ctrl+V).
  Se não souber o caminho agora, tecle Enter: dá para enviar o forecast pela tela *Importar*.

As respostas ficam no `caminhos.txt` (só no seu PC). Para mudar depois: rode `instalar.bat` de novo
ou edite o `caminhos.txt` no Bloco de Notas.

**4. Usar** — dê **dois cliques em `abrir_controle.bat`**. O navegador abre em http://127.0.0.1:5000.
Deixe a janela preta aberta enquanto usa; para desligar, feche a janela.

> Na primeira vez, se quiser conhecer as telas antes dos dados reais: na pasta do controle, abra o
> Prompt de Comando e rode `.venv\Scripts\python.exe dados_exemplo.py` (dados fictícios).
> Para começar do zero depois, apague a pasta `instance`.

### Forecast ligado ao arquivo (como nas atas)

Com o caminho do forecast configurado, toda vez que você abre **O que subir**, **Gestores** ou **Frentes**
o controle confere se o arquivo mudou e lê de novo sozinho (aviso verde no topo). Em **Importar** tem o
botão **Atualizar agora**. Pode ser o **arquivo** ou a **pasta** (na pasta, vale o forecast salvo por último).
O arquivo precisa estar no seu PC (pasta sincronizada do OneDrive/SharePoint serve; link `https://` não).
Se estiver aberto no Excel ou o caminho estiver errado, aparece um aviso e vale o último forecast lido.

### Primeira vez com dados reais

1. **Locais**: digite a capacidade real de cada prédio.
2. **Importar → Relatório do CMAP**: o que já está reservado (sem ele, “Disponíveis” fica zerado).
3. **Frentes**: “Preencher MAS vazios” com o controle antigo e digite os MAS que faltarem.
4. Confira **O que subir** e **Gestores**.

## Regras do cálculo (forecast → CMAP)

Do **FORECAST OFICIAL** (aba `BASE`) usamos, por frente e mês: a carga (**6H20** ou **7H12**), o **MOP**,
Home manhã/tarde e Staff incompany/home.

| O quê | Regra |
|---|---|
| PAs no prédio (PRODUCAGENT-DIR) | Integrais (7H12): MOP − Home. Frentes **6H20**: o **maior turno** — manhã e tarde dividem a PA; o MOP − Home é repartido na proporção INCOMPANY MANHÃ/TARDE do forecast (sem essa divisão no arquivo: ÷ 2) |
| Home office | reserva separada em *WAH Brasil Direto WFH* (`_HO`) com o Home |
| Staff (TEAMLEADER-DIR) | Staff incompany no prédio; Staff home na reserva `_HO` |
| Arredondamento | **sempre para cima**, depois de somar tudo do mesmo MAS + local |

O endereço do forecast vira o Location ID do CMAP pelo nome (ex.: “Curitiba Marechal 3” → `BR-CUR-MALDE-02`;
andar “HOME OFFICE” → `BR-WFH-DIRETO`). Avisos da importação mostram frentes sem 6H20/7H12, FATOR PA do
arquivo diferente da regra e endereços não reconhecidos.

## Rotina sugerida

1. O forecast entra sozinho pelo `caminhos.txt` (ou envie em **Importar**). Importe o **relatório do CMAP**
   sempre que quiser conferir o que está lançado.
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
configurar.py     perguntas do instalar.bat (nome e caminho do forecast)
instalar.bat      instalação (dois cliques, uma vez)
abrir_controle.bat  abre o controle no navegador
templates/        HTML de cada tela
static/           estilo (CSS) e JavaScript
tests/            testes automáticos  ->  python -m pytest
```

## Identidade visual

Cores oficiais da Concentrix (arquivo `CNX_RGB+Tints.ase`), definidas como variáveis no topo de
`static/estilo.css` (`--cnx-azul`, `--cnx-jade`, `--cnx-seafoam`...). Logo branco (`CNX_Reverse_RGB.svg`)
e ícone em `static/marca/`. Funciona no tema claro e no escuro do sistema.
