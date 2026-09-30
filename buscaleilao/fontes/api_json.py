"""Fonte genérica para sites que carregam os lotes via API JSON.

Muitos sites de leilão modernos montam a página no navegador a partir de uma
API (veja a aba "Rede/Network" do DevTools). Consumir essa API é bem mais
estável do que raspar o HTML. Exemplo de configuração:

    {
      "id": "leiloeiro_y",
      "tipo": "json",
      "url": "https://api.leiloeiroy.com.br/lotes?page={pagina}&size=100",
      "paginas": 20,
      "caminho_lista": "data.content",
      "campos": {
        "id_externo": "id",
        "titulo": "descricao",
        "marca": "veiculo.marca",
        "modelo": "veiculo.modelo",
        "ano_modelo": "veiculo.anoModelo",
        "monta": "veiculo.tipoMonta",
        "lance_atual": "valorLanceAtual",
        "data_leilao": "leilao.dataInicio",
        "leilao": "leilao.nome",
        "imagem_url": "fotos.0.url",
        "_leilao_id": "leilao.id"
      },
      "formatos": {"url": "https://www.leiloeiroy.com.br/leilao/{_leilao_id}/lote/{id_externo}"}
    }

Caminhos usam ponto para navegar em objetos e números para índices de lista.

Paginação: a URL e o corpo da requisição aceitam os marcadores {pagina}
(1, 2, 3...), {pagina0} (0, 1, 2...) e {deslocamento} ((pagina - 1) x
"tamanho_pagina"). O corpo pode ser JSON ("corpo") ou formulário
("corpo_form", como texto já codificado). Com "navegador": true as chamadas
são feitas de dentro de um navegador de verdade (sites com proteção
anti-robô). "formatos", "constantes" e "excluir": veja fontes.base.montar_lote.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from ..modelos import Lote
from .base import Fonte, criar_cliente, montar_lote

log = logging.getLogger(__name__)


def pegar(dados: Any, caminho: str | None) -> Any:
    if not caminho:
        return dados
    atual = dados
    for parte in caminho.split("."):
        if isinstance(atual, list) and parte.isdigit():
            idx = int(parte)
            atual = atual[idx] if idx < len(atual) else None
        elif isinstance(atual, dict):
            atual = atual.get(parte)
        else:
            return None
        if atual is None:
            return None
    return atual


def _marcadores(pagina: int, tamanho: int) -> dict[str, int]:
    return {"pagina": pagina, "pagina0": pagina - 1, "deslocamento": (pagina - 1) * tamanho}


def _preencher(valor: Any, marcadores: dict[str, int]) -> Any:
    """Substitui {pagina}, {pagina0} e {deslocamento}; se o valor for só o
    marcador, vira número."""
    if isinstance(valor, str):
        for nome, numero in marcadores.items():
            if valor == "{" + nome + "}":
                return numero
            valor = valor.replace("{" + nome + "}", str(numero))
        return valor
    if isinstance(valor, dict):
        return {k: _preencher(v, marcadores) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_preencher(v, marcadores) for v in valor]
    return valor


class FonteApiJson(Fonte):
    tipo = "json"

    def __init__(self, id: str, nome: str | None = None, cliente=None, **config):
        super().__init__(id, nome, **config)
        self.cliente = cliente or criar_cliente(config)

    def extrair_resposta(self, dados: Any) -> list[Lote]:
        itens = pegar(dados, self.config.get("caminho_lista")) or []
        campos: dict = self.config["campos"]
        config = dict(self.config)
        if self.config.get("url_lote"):  # forma antiga de "formatos": {"url": ...}
            config["formatos"] = {"url": self.config["url_lote"], **config.get("formatos", {})}
        lotes = []
        for item in itens:
            valores = {campo: pegar(item, caminho) for campo, caminho in campos.items()}
            valores = {k: (str(v) if isinstance(v, (dict, list)) else v) for k, v in valores.items()}
            if valores.get("id_externo") is not None:
                valores["id_externo"] = str(valores["id_externo"])
            lote = montar_lote(self.id, valores, config, url_base=self.config.get("url_base"))
            if lote:
                lotes.append(lote)
        return lotes

    def coletar(self, max_paginas: int | None = None) -> Iterable[Lote]:
        url = self.config["url"]
        metodo = self.config.get("metodo", "GET").upper()
        paginas = self.config.get("paginas", 1)
        if max_paginas:
            paginas = min(paginas, max_paginas)
        tamanho = self.config.get("tamanho_pagina", 0)
        pagina_variavel = any(
            "{" + m + "}" in str(self.config.get(chave, ""))
            for m in ("pagina", "pagina0", "deslocamento")
            for chave in ("url", "corpo", "corpo_form")
        )
        vistos: set[str] = set()
        for pagina in range(1, paginas + 1):
            marcadores = _marcadores(pagina, tamanho)
            kwargs = {}
            if "corpo" in self.config:
                kwargs["json"] = _preencher(self.config["corpo"], marcadores)
            elif "corpo_form" in self.config:
                kwargs["data"] = _preencher(self.config["corpo_form"], marcadores)
            resp = self.cliente.requisitar(_preencher(url, marcadores), metodo, **kwargs)
            lotes = [l for l in self.extrair_resposta(resp.json()) if l.id_externo not in vistos]
            log.info("%s: página %d -> %d lotes", self.id, pagina, len(lotes))
            if not lotes:
                break
            for lote in lotes:
                vistos.add(lote.id_externo)
                yield lote
            if not pagina_variavel:
                break
