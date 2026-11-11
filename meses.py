"""
meses.py — tudo sobre meses.

O CMAP trabalha com uma janela de 12 meses (ex.: Nov-2026 até Oct-2027).
Aqui guardamos o mês como "AAAA-MM" no banco (ex.: "2026-11") e mostramos
na tela como o CMAP mostra (ex.: "Nov-2026").
"""
from dataclasses import dataclass
from datetime import date, datetime

# O CMAP usa os nomes dos meses em inglês, então seguimos o mesmo padrão.
NOMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True, order=True)
class Mes:
    ano: int
    mes: int

    @property
    def chave(self) -> str:
        """Como o mês fica salvo no banco: '2026-11'."""
        return f"{self.ano:04d}-{self.mes:02d}"

    @property
    def rotulo(self) -> str:
        """Como o mês aparece na tela, igual ao CMAP: 'Nov-2026'."""
        return f"{NOMES[self.mes - 1]}-{self.ano}"

    @property
    def primeiro_dia(self) -> date:
        return date(self.ano, self.mes, 1)

    def somar(self, n: int) -> "Mes":
        """Anda n meses para frente (ou para trás, se n for negativo)."""
        total = self.ano * 12 + (self.mes - 1) + n
        return Mes(total // 12, total % 12 + 1)


def atual(hoje: date | None = None) -> Mes:
    hoje = hoje or date.today()
    return Mes(hoje.year, hoje.month)


def janela(inicio: Mes | None = None, quantidade: int = 12) -> list[Mes]:
    """Os 12 meses que aparecem nas telas, começando no mês atual."""
    inicio = inicio or atual()
    return [inicio.somar(i) for i in range(quantidade)]


def de_chave(chave: str) -> Mes:
    ano, mes = chave.split("-")
    return Mes(int(ano), int(mes))


def de_valor(valor) -> Mes:
    """
    Converte o que vem da planilha (data do Excel ou texto) em Mes.
    Aceita: datetime/date, '2026-11', '2026-11-01', '11/1/2026', 'Nov-2026'.
    """
    if isinstance(valor, (datetime, date)):
        return Mes(valor.year, valor.month)
    texto = str(valor).strip()
    if "/" in texto:                       # formato americano M/D/AAAA
        partes = texto.split("/")
        return Mes(int(partes[2][:4]), int(partes[0]))
    if texto[:3].title() in NOMES and "-" in texto:   # 'Nov-2026'
        return Mes(int(texto.split("-")[1]), NOMES.index(texto[:3].title()) + 1)
    ano, mes = texto.split("-")[:2]        # '2026-11' ou '2026-11-01'
    return Mes(int(ano), int(mes))


def restrito(m: Mes, hoje: date | None = None) -> bool:
    """
    No CMAP, o mês atual e o próximo aparecem em rosa ("Alteração Restrita").
    Aqui fazemos o mesmo destaque para avisar que mudar esses meses
    precisa de mais cuidado.
    """
    agora = atual(hoje)
    return m in (agora, agora.somar(1))
