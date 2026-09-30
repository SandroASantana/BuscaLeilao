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
"@atributo" pega o atributo do próprio item. Acrescentando "|re:REGEX", fica
só o trecho capturado pela regex (os grupos são unidos por "-"), por exemplo
"a@href|re:loteId=(\d+)".

Outras opções:
- "urls": lista de URLs de listagem, no lugar de "url" (ex.: uma por categoria);
- "navegador": true para usar um navegador de verdade (sites com proteção
  anti-robô); com "renderizar": true a página é montada pelo navegador antes
  de ser lida (sites que carregam os lotes por JavaScript);
- "formatos", "constantes" e "excluir": veja fontes.base.montar_lote.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from ..modelos import Lote
from .base import Fonte, criar_cliente, montar_lote

log = logging.getLogger(__name__)


def extrair(item: Tag, seletor: str) -> str | None:
    seletor, _, regex = seletor.partition("|re:")
    css, _, atributo = seletor.partition("@")
    alvo = item.select_one(css) if css.strip() else item
    if alvo is None:
        return None
    if atributo:
        valor = alvo.get(atributo)
        if isinstance(valor, list):
            valor = " ".join(valor)
    else:
        valor = alvo.get_text(" ", strip=True)
    if regex and valor is not None:
        m = re.search(regex, valor)
        if not m:
            return None
        valor = "-".join(g for g in m.groups() if g) if m.groups() else m.group(0)
    return valor


class FonteHtml(Fonte):
    tipo = "html"

    def __init__(self, id: str, nome: str | None = None, cliente=None, **config):
        super().__init__(id, nome, **config)
        if "url" not in config and config.get("urls"):
            config["url"] = config["urls"][0]
        self.cliente = cliente or criar_cliente(config)

    def extrair_pagina(self, html: str, url_pagina: str) -> list[Lote]:
        seletores = dict(self.config["seletores"])
        seletor_item = seletores.pop("item")
        soup = BeautifulSoup(html, "html.parser")
        lotes = []
        for item in soup.select(seletor_item):
            dados = {campo: extrair(item, sel) for campo, sel in seletores.items()}
            lote = montar_lote(self.id, dados, self.config, url_base=url_pagina)
            if lote:
                lotes.append(lote)
        return lotes

    def coletar(self, max_paginas: int | None = None) -> Iterable[Lote]:
        vistos: set[str] = set()
        for url in self.config.get("urls") or [self.config["url"]]:
            paginas = self.config.get("paginas", 1) if "{pagina}" in url else 1
            if max_paginas:
                paginas = min(paginas, max_paginas)
            for pagina in range(1, paginas + 1):
                url_pagina = url.format(pagina=pagina)
                resp = self.cliente.requisitar(url_pagina, renderizar=self.config.get("renderizar", False))
                lotes = [l for l in self.extrair_pagina(resp.text, url_pagina) if l.id_externo not in vistos]
                log.info("%s: %s -> %d lotes", self.id, url_pagina, len(lotes))
                if not lotes:
                    break
                for lote in lotes:
                    vistos.add(lote.id_externo)
                    yield lote
