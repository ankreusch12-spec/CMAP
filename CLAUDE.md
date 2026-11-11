# Controle CMAP — regras do projeto

- Idioma: português (código, comentários, telas e mensagens de commit).
- Público: o código precisa ser **didático** — funções curtas, comentários explicando o porquê.
- Padrão do CMAP: manter os mesmos nomes de campos, códigos de local (BR-XXX-...), Dept Codes,
  Shift e meses no formato `Nov-2026`. Mudanças de layout devem continuar parecidas com as telas do CMAP.
- Segurança: seguir `SEGURANCA.md` e a skill `seguranca-cmap` antes de qualquer mudança.
  Nunca colocar dados reais da empresa no repositório; exemplos e testes são fictícios.
- Stack: Python + Flask + SQLite + openpyxl, sem dependências de front-end externas.
- Rodar: `python app.py` (http://127.0.0.1:5000). Testes: `python -m pytest`.
