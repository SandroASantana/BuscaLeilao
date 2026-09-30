from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from buscaleilao.banco import Banco
from buscaleilao.coletor import coletar
from buscaleilao.fontes import criar_fonte
from buscaleilao.web.app import criar_app

RAIZ = Path(__file__).parent.parent


@pytest.fixture
def cliente(tmp_path):
    caminho = tmp_path / "t.db"
    fonte = criar_fonte({"id": "demo", "tipo": "arquivo", "caminho": str(RAIZ / "dados/exemplo_lotes.json")})
    coletar(Banco(caminho), [fonte])
    return TestClient(criar_app(caminho))


def test_pagina(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "BuscaLeilão" in r.text


def test_api_lotes_com_filtros_multiplos(cliente):
    tudo = cliente.get("/api/lotes").json()
    assert tudo["total"] == 60
    r = cliente.get("/api/lotes", params=[("categoria", "moto"), ("categoria", "caminhao")]).json()
    assert r["total"] > 0
    assert {l["categoria"] for l in r["lotes"]} <= {"moto", "caminhao"}
    r = cliente.get("/api/lotes", params={"monta": "grande", "limite": 5}).json()
    assert all(l["monta"] == "grande" for l in r["lotes"])


def test_api_facetas_e_leiloes(cliente):
    f = cliente.get("/api/facetas").json()
    assert sum(x["total"] for x in f["categoria"]) == 60
    leiloes = cliente.get("/api/leiloes").json()
    assert len(leiloes) == 4
    assert sum(l["total"] for l in leiloes) == 60
    um = leiloes[0]
    r = cliente.get("/api/lotes", params={"fonte": um["fonte"], "leilao": um["leilao"]}).json()
    assert r["total"] == um["total"]


def test_api_detalhe(cliente):
    assert cliente.get("/api/lotes/demo/1-001").json()["id_externo"] == "1-001"
    assert cliente.get("/api/lotes/demo/nao-existe").status_code == 404
