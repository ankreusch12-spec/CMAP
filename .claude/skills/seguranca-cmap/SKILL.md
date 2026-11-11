---
name: seguranca-cmap
description: Checklist de segurança e padrões do Controle CMAP. Use antes de criar ou alterar qualquer página, rota, formulário, importação/exportação de Excel ou dependência deste projeto, e antes de cada commit.
---

# Checklist de segurança — Controle CMAP

Passe por cada item ao mudar o código. Se algum item não puder ser cumprido, pare e explique ao usuário.

## Dados
- [ ] Nenhum dado real no repositório: planilhas, exports, prints, nomes de clientes, capacidades
      reais ou nomes de pessoas. Exemplos e testes usam dados fictícios (CLIENTE_A, EXEMPLO001...).
- [ ] `git status` antes do commit: nada de `*.xlsx`, `*.csv`, `*.db`, `instance/`, `.env`.

## Rotas e formulários
- [ ] Todo `<form method="post">` tem `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
- [ ] Alterações só por POST (nunca GET).
- [ ] Todo campo validado no servidor (`texto()`, `codigo()`, números ≥ 0 com limite).
- [ ] SQL sempre com `?` — nunca f-string com valor vindo do usuário.
- [ ] Toda alteração chama `banco.registrar(...)` (Histórico).

## Página
- [ ] Sem CDN, fonte ou script externo. CSS em `static/estilo.css`, JS em `static/app.js`.
- [ ] Sem `<script>` inline, `onclick=` ou `style=` no HTML (a CSP bloqueia).
- [ ] Nada de `|safe` no Jinja com dado do usuário.

## Excel
- [ ] Leitura com `load_workbook(..., read_only=True, data_only=True)`.
- [ ] Escrita sempre passando textos por `planilhas._texto()` (formula injection).

## Servidor
- [ ] Continua em `host="127.0.0.1"` e `debug=False`.
- [ ] Nada de login automatizado no CMAP/Workday nem senha guardada.

## Fechamento
- [ ] `python -m pytest` passa.
- [ ] Teste novo para a regra nova.
