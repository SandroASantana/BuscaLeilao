"""Fonte que lê lotes de um arquivo JSON local.

Útil para importar dados exportados de outro sistema, para testes e para a
demonstração (dados/exemplo_lotes.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..modelos import Lote
from .base import Fonte, lote_de_dict


class FonteArquivo(Fonte):
    tipo = "arquivo"

    def coletar(self) -> Iterable[Lote]:
        caminho = Path(self.config["caminho"])
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            dados = dados.get("lotes", [])
        constantes = self.config.get("constantes", {})
        for item in dados:
            lote = lote_de_dict(self.id, {**constantes, **item})
            if lote:
                yield lote
