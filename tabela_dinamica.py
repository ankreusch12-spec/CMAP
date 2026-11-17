"""
tabela_dinamica.py — lê os dados guardados no CACHE de uma tabela dinâmica do Excel.

Por que existe: na planilha BRA_Distribution_Capacity, a aba "12 month forecast" é uma
tabela dinâmica montada a partir do relatório do CMAP. A aba de origem não vem no
arquivo, mas o Excel guarda uma cópia de todas as linhas dentro do .xlsx
(xl/pivotCache/pivotCacheRecords1.xml). Aqui lemos essa cópia.

Um .xlsx é um ZIP com arquivos XML. Em cada tabela dinâmica:
  pivotCacheDefinitionN.xml  -> nomes das colunas e listas de valores repetidos
  pivotCacheRecordsN.xml     -> as linhas; cada valor vem escrito ou como um
                                número <x v="3"/> que aponta para a lista acima
"""
import posixpath
import re
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
LIMITE_BYTES = 300 * 1024 * 1024        # proteção contra arquivo "inflado" de propósito


def _valor(elemento):
    """Converte um valor do cache (<s>, <n>, <d>, <b>, <m>, <e>) para Python."""
    tipo = elemento.tag.replace(NS, "")
    v = elemento.get("v")
    if tipo == "n":
        numero = float(v)
        return int(numero) if numero.is_integer() else numero
    if tipo == "d":
        return datetime.fromisoformat(v)
    if tipo == "b":
        return v in ("1", "true")
    if tipo == "m":                      # valor em branco
        return None
    return v                             # texto (s) ou erro (e)


def _campos(definicao):
    """Colunas que têm valor em cada linha + listas de valores repetidos de cada uma."""
    nomes, listas = [], []
    for campo in definicao.iter(NS + "cacheField"):
        if campo.get("databaseField") == "0":    # agrupamentos (Meses, Trimestres...) não vêm nas linhas
            continue
        compartilhados = campo.find(NS + "sharedItems")
        nomes.append(campo.get("name", ""))
        listas.append([_valor(e) for e in compartilhados] if compartilhados is not None else [])
    return nomes, listas


def ler(arquivo, obrigatorias: set):
    """
    Procura uma tabela dinâmica cujas colunas incluam `obrigatorias` (minúsculas).
    Devolve (nomes das colunas, lista de linhas) ou None se não achar.
    """
    try:
        pacote = zipfile.ZipFile(arquivo)
    except zipfile.BadZipFile:
        return None
    with pacote:
        definicoes = sorted(n for n in pacote.namelist()
                            if re.fullmatch(r"xl/pivotCache/pivotCacheDefinition\d+\.xml", n))
        for nome_def in definicoes:
            definicao = ET.fromstring(pacote.read(nome_def))
            nomes, listas = _campos(definicao)
            if not obrigatorias <= {n.strip().lower() for n in nomes}:
                continue
            caminho = _arquivo_das_linhas(pacote, nome_def, definicao)
            if not caminho or pacote.getinfo(caminho).file_size > LIMITE_BYTES:
                continue
            return nomes, list(_linhas(pacote, caminho, listas))
    return None


def _arquivo_das_linhas(pacote, nome_def, definicao):
    """Segue o "endereço" (relationship) da definição até o arquivo com as linhas."""
    rels = posixpath.join(posixpath.dirname(nome_def), "_rels", posixpath.basename(nome_def) + ".rels")
    if rels not in pacote.namelist():
        return None
    rid = definicao.get(NS_R + "id")
    for rel in ET.fromstring(pacote.read(rels)):
        if rel.get("Id") == rid:
            return posixpath.normpath(posixpath.join(posixpath.dirname(nome_def), rel.get("Target")))
    return None


def _linhas(pacote, caminho, listas):
    """Lê as linhas aos poucos (iterparse), sem carregar o XML inteiro na memória."""
    with pacote.open(caminho) as arquivo:
        for _evento, elemento in ET.iterparse(arquivo):
            if elemento.tag != NS + "r":
                continue
            linha = []
            for i, valor in enumerate(elemento):
                if valor.tag == NS + "x":                       # aponta para a lista
                    indice = int(valor.get("v"))
                    lista = listas[i] if i < len(listas) else []
                    linha.append(lista[indice] if indice < len(lista) else None)
                else:
                    linha.append(_valor(valor))
            elemento.clear()
            yield linha
