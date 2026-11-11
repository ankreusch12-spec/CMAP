# Segurança — como o Controle CMAP protege os dados

Este documento resume as decisões de segurança. Se a política da empresa pedir algo
diferente, **a política da empresa vale** — ajuste aqui e no código.

## 1. Os dados não saem do seu PC
- O repositório guarda só **código**. O `.gitignore` bloqueia `*.xlsx`, `*.csv`, `*.db`,
  a pasta `instance/` (banco + chave secreta) e arquivos `.env`.
- O banco é um arquivo SQLite local: `instance/cmap.db`.
- Os dados de exemplo (`dados_exemplo.py`) são **fictícios**.
- **Nunca** faça commit de planilha, print ou export com dados reais (nomes de clientes,
  capacidades, nomes de pessoas).

## 2. Só o seu PC acessa a página
- O servidor sobe em `127.0.0.1` (não aparece na rede).
- Requisições com outro endereço (`Host`) são recusadas — evita ataques de *DNS rebinding*.

## 3. Formulários protegidos
- Todo formulário tem um **token CSRF**: outro site não consegue enviar dados “em seu nome”.
- Cookie de sessão `HttpOnly` e `SameSite=Strict`.
- Tudo o que é digitado é validado no servidor (tamanho, formato de códigos, números ≥ 0).
- Consultas SQL sempre com parâmetros (`?`) — sem *SQL injection*.
- O HTML escapa tudo automaticamente (Jinja) — sem *XSS*.

## 4. A página não carrega nada de fora
- Sem CDN, fontes ou scripts externos: CSS e JS ficam em `static/`.
- Cabeçalho `Content-Security-Policy` só permite recursos do próprio controle,
  e a página não pode ser embutida em outro site (`frame-ancestors 'none'`).

## 5. Importação e exportação de Excel
- Upload: só `.xlsx`, até 20 MB, conferindo a assinatura do arquivo; lido em modo
  somente leitura, sem executar fórmulas nem macros; o arquivo é descartado após a leitura.
- Exportação: textos que começam com `= + - @` recebem `'` na frente, para o Excel não
  executá-los como fórmula (*formula injection*).

## 6. Rastreabilidade
- Toda criação, alteração, importação e exclusão vai para o **Histórico**, com data e usuário.

## 7. O CMAP (Archibus)
- O controle **não** faz login no CMAP nem guarda senha. O acesso ao CMAP continua pelo
  login da empresa (Workday). A troca de dados é por **arquivo** (importar/exportar Excel).
- Qualquer integração automática com o CMAP só com aprovação do TI/Segurança e por meio
  oficial (API ou importação do Archibus), nunca automatizando o login.

## Antes de cada mudança no código
Use o checklist da skill `seguranca-cmap` (`.claude/skills/seguranca-cmap/SKILL.md`)
e rode os testes: `python -m pytest`.
