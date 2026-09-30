"""Fonte que lê lotes de um arquivo JSON local.

Útil para importar dados exportados de outro sistema, para testes e para a
demonstração (dados/exemplo_lotes.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..modelos import Lote
from .base import Fonte, montar_lote


class FonteArquivo(Fonte):
    tipo = "arquivo"

    def coletar(self, max_paginas: int | None = None) -> Iterable[Lote]:
        caminho = Path(self.config["caminho"])
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            dados = dados.get("lotes", [])
        for item in dados:
            lote = montar_lote(self.id, item, self.config)
            if lote:
                yield lote
