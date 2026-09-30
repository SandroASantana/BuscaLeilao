from datetime import datetime, timedelta

import pytest

from buscaleilao.banco import Banco, Filtros
from buscaleilao.modelos import Lote
from buscaleilao.normalizacao import normalizar_lote


def _lote(id_, titulo, **kw):
    kw.setdefault("leilao", "Leilão A")
    return normalizar_lote(Lote(fonte=kw.pop("fonte", "f1"), id_externo=id_, titulo=titulo, **kw))


@pytest.fixture
def banco(tmp_path):
    b = Banco(tmp_path / "t.db")
    futuro = datetime.now() + timedelta(days=5)
    b.salvar([
        _lote("1", "VW/GOL 1.0 2015/2016", monta="Pequena monta", lance_inicial=15000,
              cidade="Campinas/SP", data_leilao=futuro),
        _lote("2", "FIAT/STRADA 1.4 2019/2020", monta="Grande monta", lance_inicial=30000,
              cidade="Curitiba/PR", data_leilao=futuro),
        _lote("3", "HONDA/CG 160 FAN 2021", lance_inicial=8000, leilao="Leilão B",
              cidade="Campinas/SP", data_leilao=datetime.now() - timedelta(days=5)),
    ])
    b.salvar([_lote("9", "TOYOTA/COROLLA 2.0 2020", fonte="f2", leilao="Leilão C")])
    return b


def ids(resultado):
    return sorted(l["id_externo"] for l in resultado["lotes"])


def test_filtros_basicos(banco):
    assert banco.buscar()["total"] == 4
    assert ids(banco.buscar(Filtros(categoria=["moto"]))) == ["3"]
    assert ids(banco.buscar(Filtros(marca=["vw", "fiat"]))) == ["1", "2"]
    assert ids(banco.buscar(Filtros(monta=["grande"]))) == ["2"]
    assert ids(banco.buscar(Filtros(monta=["Pequena Monta"]))) == ["1"]
    assert ids(banco.buscar(Filtros(uf=["sp"]))) == ["1", "3"]
    assert ids(banco.buscar(Filtros(ano_min=2019))) == ["2", "3", "9"]
    assert ids(banco.buscar(Filtros(lance_max=16000))) == ["1", "3"]
    assert ids(banco.buscar(Filtros(fonte=["f2"]))) == ["9"]
    assert ids(banco.buscar(Filtros(leilao=["Leilão B"]))) == ["3"]
    assert ids(banco.buscar(Filtros(apenas_futuros=True))) == ["1", "2", "9"]


def test_busca_textual_ignora_acento_e_caixa(banco):
    assert ids(banco.buscar(Filtros(texto="gol campinas"))) == ["1"]
    assert ids(banco.buscar(Filtros(texto="CURITÍBA"))) == ["2"]
    assert ids(banco.buscar(Filtros(texto="leilão  B honda"))) == ["3"]


def test_ordenacao_e_paginacao(banco):
    r = banco.buscar(ordem="lance", limite=2, pagina=1)
    assert [l["id_externo"] for l in r["lotes"]] == ["3", "1"]
    assert r["total"] == 4
    r2 = banco.buscar(ordem="lance", limite=2, pagina=2)
    assert [l["id_externo"] for l in r2["lotes"]] == ["2", "9"]


def test_facetas(banco):
    f = banco.facetas(Filtros(fonte=["f1"]))
    categorias = {x["valor"]: x["total"] for x in f["categoria"]}
    assert categorias == {"carro": 1, "utilitario": 1, "moto": 1}
    assert f["faixas"]["lance_min"] == 8000
    # a faceta ignora o próprio filtro, mas respeita os demais
    f = banco.facetas(Filtros(fonte=["f1"], categoria=["moto"]))
    assert {x["valor"]: x["total"] for x in f["categoria"]} == {"carro": 1, "utilitario": 1, "moto": 1}
    assert {x["valor"]: x["total"] for x in f["marca"]} == {"Honda": 1}
    assert {x["valor"]: x["total"] for x in f["fonte"]} == {"f1": 1}


def test_resumo_leiloes(banco):
    resumo = {r["leilao"]: r for r in banco.resumo_leiloes()}
    assert resumo["Leilão A"]["total"] == 2
    assert resumo["Leilão A"]["monta"] == {"pequena": 1, "grande": 1}
    assert resumo["Leilão B"]["categoria"] == {"moto": 1}


def test_upsert_e_desativacao(banco):
    atualizado = _lote("1", "VW/GOL 1.0 2015/2016", lance_inicial=17000)
    banco.salvar([atualizado], fonte="f1", desativar_ausentes=True)
    assert banco.obter("f1", "1")["lance_inicial"] == 17000
    assert ids(banco.buscar(Filtros(fonte=["f1"]))) == ["1"]
    assert banco.buscar(Filtros(fonte=["f1"], incluir_inativos=True))["total"] == 3
    # lotes de outra fonte não são afetados
    assert ids(banco.buscar(Filtros(fonte=["f2"]))) == ["9"]
