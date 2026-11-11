"""
seguranca.py — as proteções da aplicação, num lugar só.

Resumo do que está aqui (detalhes em SEGURANCA.md):
  1. Chave secreta gerada no seu PC (nunca vai para o GitHub).
  2. Token CSRF em todo formulário: impede que outro site envie
     formulários "em seu nome" para o controle.
  3. Só aceita acessos pelo próprio PC (127.0.0.1 / localhost).
  4. Cabeçalhos de segurança: nada de scripts ou estilos de fora,
     a página não pode ser embutida em outro site, etc.
"""
import os
import secrets

from flask import abort, request, session

HOSTS_LOCAIS = {"127.0.0.1", "localhost"}


def chave_secreta(pasta: str) -> str:
    """Lê (ou cria na primeira vez) a chave secreta em instance/secret_key."""
    caminho = os.path.join(pasta, "secret_key")
    if not os.path.exists(caminho):
        with open(caminho, "w", encoding="utf-8") as arq:
            arq.write(secrets.token_hex(32))
        try:
            os.chmod(caminho, 0o600)        # só o seu usuário lê
        except OSError:
            pass
    with open(caminho, encoding="utf-8") as arq:
        return arq.read().strip()


def token_csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def iniciar(app):
    # Deixa {{ csrf_token() }} disponível em todos os templates.
    app.jinja_env.globals["csrf_token"] = token_csrf

    # Hosts extras permitidos (ex.: visualização). Padrão: só o próprio PC.
    extras = {h.strip() for h in os.environ.get("CMAP_HOSTS", "").split(",") if h.strip()}

    @app.before_request
    def checar_requisicao():
        # (3) Só responde para endereços locais. Protege contra
        # "DNS rebinding" (um site tentando ler o controle pelo navegador).
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        # CMAP_HOSTS=* desliga esta checagem: use SÓ em ambiente de visualização
        # isolado, nunca no PC com dados reais.
        if not app.testing and "*" not in extras and host not in HOSTS_LOCAIS | extras:
            abort(403)

        # (2) Todo POST precisa trazer o token CSRF da sessão.
        if request.method == "POST":
            enviado = request.form.get("csrf_token", "")
            esperado = session.get("csrf", "")
            if not enviado or not esperado or not secrets.compare_digest(enviado, esperado):
                abort(400, "Formulário expirado ou inválido. Recarregue a página.")

    @app.after_request
    def cabecalhos(resposta):
        # (4) Cabeçalhos de segurança.
        resposta.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; object-src 'none'"
        )
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        resposta.headers["Cache-Control"] = "no-store"
        return resposta
