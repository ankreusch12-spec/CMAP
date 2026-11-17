"""
pastas.py — onde ficam os dados e a configuração do controle.

Por que uma pasta fixa: o programa pode estar em qualquer lugar (e mudar de lugar a cada
atualização, quando você extrai um ZIP novo). Os DADOS não podem ir junto com o programa,
senão cada cópia começa vazia. Por isso ficam numa pasta fixa do seu usuário no Windows:

    %LOCALAPPDATA%\\ControleCMAP\\        (ex.: C:\\Users\\voce\\AppData\\Local\\ControleCMAP)
        cmap.db        o banco (reservas, forecast, lançamentos, histórico)
        secret_key     a chave de segurança
        caminhos.txt   seu nome e o caminho do forecast
        venv\\          as bibliotecas do controle (instaladas uma vez pelo instalar.bat)

Essa pasta não fica no OneDrive (não sincroniza) e é só do seu usuário.
Fora do Windows (testes), usa a pasta "instance" ao lado do programa.
"""
import os
import shutil
from pathlib import Path

PROGRAMA = Path(__file__).resolve().parent


def pasta_dados() -> Path:
    """A pasta fixa dos dados (pode ser trocada pela variável CMAP_DADOS)."""
    if os.environ.get("CMAP_DADOS"):
        pasta = Path(os.environ["CMAP_DADOS"])
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        pasta = Path(os.environ["LOCALAPPDATA"]) / "ControleCMAP"
    else:
        pasta = PROGRAMA / "instance"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def trazer_dados_antigos(destino: Path):
    """
    Versões anteriores guardavam tudo ao lado do programa (pasta instance e caminhos.txt).
    Se a pasta fixa ainda não tem esses arquivos, copia de lá — nada se perde.
    """
    antigos = [(PROGRAMA / "instance" / "cmap.db", destino / "cmap.db"),
               (PROGRAMA / "instance" / "secret_key", destino / "secret_key"),
               (PROGRAMA / "caminhos.txt", destino / "caminhos.txt")]
    for origem, alvo in antigos:
        if origem.exists() and not alvo.exists() and origem.resolve() != alvo.resolve():
            shutil.copy2(origem, alvo)
