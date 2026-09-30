"""Fonte genérica para sites de leilão que listam os lotes em HTML.

Em vez de escrever um raspador em Python para cada leiloeiro, descreve-se o
site com seletores CSS na configuração (config/fontes.json):

    {
      "id": "leiloeiro_x",
      "tipo": "html",
      "nome": "Leiloeiro X",
      "url": "https://www.leiloeirox.com.br/veiculos?pagina={pagina}",
      "paginas": 5,
      "seletores": {
        "item": "div.card-lote",           # um elemento por lote
        "id_externo": "@data-lote",        # atributo do próprio item
        "titulo": "h2.titulo",             # texto do elemento
        "url": "a.link@href",              # atributo de um elemento interno
        "lance_atual": ".valor-lance",
        "data_leilao": ".data-leilao",
        "cidade": ".local",
        "imagem_url": "img@src"
      },
      "constantes": {"categoria": "carro"}
    }

Sintaxe do seletor: "css" pega o texto; "css@atributo" pega um atributo;
"@atributo" pega o atributo do próprio item.
"""

from __future__ import annotations

import logging
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from ..modelos import Lote
from .base import ClienteHttp, Fonte, lote_de_dict

log = logging.getLogger(__name__)


def extrair(item: Tag, seletor: str) -> str | None:
    css, _, atributo = seletor.partition("@")
    alvo = item.select_one(css) if css.strip() else item
    if alvo is None:
        return None
    if atributo:
        valor = alvo.get(atributo)
        if isinstance(valor, list):
            valor = " ".join(valor)
        return valor
    return alvo.get_text(" ", strip=True)


class FonteHtml(Fonte):
    tipo = "html"

    def __init__(self, id: str, nome: str | None = None, cliente: ClienteHttp | None = None, **config):
        super().__init__(id, nome, **config)
        self.cliente = cliente or ClienteHttp(
            intervalo=config.get("intervalo", 1.5),
            respeitar_robots=config.get("respeitar_robots", True),
            cabecalhos=config.get("cabecalhos"),
        )

    def extrair_pagina(self, html: str, url_pagina: str) -> list[Lote]:
        seletores = dict(self.config["seletores"])
        seletor_item = seletores.pop("item")
        constantes = self.config.get("constantes", {})
        soup = BeautifulSoup(html, "html.parser")
        lotes = []
        for item in soup.select(seletor_item):
            dados = {campo: extrair(item, sel) for campo, sel in seletores.items()}
            lote = lote_de_dict(self.id, {**constantes, **dados}, url_base=url_pagina)
            if lote:
                lotes.append(lote)
        return lotes

    def coletar(self) -> Iterable[Lote]:
        url = self.config["url"]
        paginas = self.config.get("paginas", 1) if "{pagina}" in url else 1
        vistos: set[str] = set()
        for pagina in range(1, paginas + 1):
            url_pagina = url.format(pagina=pagina)
            resp = self.cliente.requisitar(url_pagina)
            lotes = [l for l in self.extrair_pagina(resp.text, url_pagina) if l.id_externo not in vistos]
            log.info("%s: página %d -> %d lotes", self.id, pagina, len(lotes))
            if not lotes:
                break
            for lote in lotes:
                vistos.add(lote.id_externo)
                yield lote
