"""
configurar.py — cria (ou atualiza) o caminhos.txt com duas perguntas simples.

O instalar.bat chama este arquivo. Também dá para rodar sozinho para trocar
o nome ou o caminho do forecast:   .venv\\Scripts\\python.exe configurar.py
"""
from pathlib import Path

import forecast

PASTA = Path(__file__).resolve().parent
ARQUIVO = PASTA / "caminhos.txt"


def perguntar_nome(atual: str) -> str:
    print("\n1) Seu nome — aparece no Histórico e em 'Criado por' das reservas.")
    resposta = input(f"   Nome [{atual or 'Usuário local'}]: ").strip()
    return resposta or atual


def perguntar_forecast(atual: str) -> str:
    print("\n2) Onde fica o FORECAST OFICIAL?")
    print("   No Explorador: Shift + botão direito no arquivo (ou na pasta) > Copiar como caminho.")
    print("   Cole aqui com Ctrl+V (ou botão direito) e tecle Enter. Enter vazio = manter/pular.")
    while True:
        resposta = input(f"   Caminho [{atual or 'nenhum'}]: ").strip().strip('"').strip()
        if not resposta:
            return atual
        achado = forecast.achar_arquivo(resposta)
        if achado:
            print(f"   OK! Forecast encontrado: {achado.name}")
            return resposta
        print("   Não achei um forecast nesse caminho (arquivo .xlsx com as colunas LOB WFM e DADO).")
        print("   Confira e cole de novo, ou tecle Enter para pular por enquanto.")


def salvar(nome: str, caminho: str):
    linhas = ["# Criado pelo configurar.py. Pode editar no Bloco de Notas.",
              "# Este arquivo é só do seu PC (não vai para o GitHub)."]
    if nome:
        linhas.append(f"usuario = {nome}")
    if caminho:
        linhas.append(f"forecast = {caminho}")
    ARQUIVO.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main():
    atual = forecast.ler_caminhos(ARQUIVO)
    print("=" * 60)
    print(" Controle CMAP - configuração")
    print("=" * 60)
    nome = perguntar_nome(atual.get("usuario", ""))
    caminho = perguntar_forecast(atual.get("forecast", ""))
    salvar(nome, caminho)
    print(f"\nPronto! Configuração salva em {ARQUIVO.name}.")


if __name__ == "__main__":
    main()
