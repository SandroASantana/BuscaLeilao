from datetime import datetime

import pytest

from buscaleilao.modelos import Lote
from buscaleilao.normalizacao import (
    encontrar_marca, extrair_anos, inferir_categoria, normalizar_condicao, normalizar_lote,
    normalizar_marca, normalizar_monta, parse_data, parse_dinheiro, separar_cidade_uf,
)


@pytest.mark.parametrize("entrada,esperado", [
    ("VW", "Volkswagen"), ("vw", "Volkswagen"), ("GM", "Chevrolet"), ("M.BENZ", "Mercedes-Benz"),
    ("Citroen", "Citroën"), ("MMC", "Mitsubishi"), ("marca nova", "Marca Nova"), (None, None),
])
def test_normalizar_marca(entrada, esperado):
    assert normalizar_marca(entrada) == esperado


def test_encontrar_marca_em_texto_livre():
    assert encontrar_marca("Caminhão Mercedes Benz Accelo 1016") == "Mercedes-Benz"
    assert encontrar_marca("sem marca aqui") is None


@pytest.mark.parametrize("entrada,esperado", [
    ("PEQUENA MONTA", "pequena"), ("Média Monta", "media"), ("monta: grande", "grande"),
    ("Sem monta", "sem_monta"), ("sem sinistro", "sem_monta"), ("sinistro com grande monta na traseira", "grande"), ("", None),
    ("veículo em bom estado", None),
])
def test_normalizar_monta(entrada, esperado):
    assert normalizar_monta(entrada) == esperado


@pytest.mark.parametrize("texto,marca,esperado", [
    ("HONDA/CG 160 FAN", "Honda", "moto"),
    ("HONDA/CIVIC EXL", "Honda", "carro"),
    ("YAMAHA/FAZER 250", "Yamaha", "moto"),
    ("TOYOTA/HILUX SRV", "Toyota", "utilitario"),
    ("VOLVO/FH 540 6X4", "Volvo", "caminhao"),
    ("SCANIA/R 450", "Scania", "caminhao"),
    ("Trator agrícola Valtra", None, "maquina"),
    ("FIAT/UNO precisa fazer revisão", "Fiat", "carro"),
])
def test_inferir_categoria(texto, marca, esperado):
    assert inferir_categoria(texto, marca) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("R$ 12.345,67", 12345.67), ("12.500", 12500.0), ("1.234.567", 1234567.0),
    ("12345.67", 12345.67), (9900, 9900.0), ("", None), ("consulte", None),
])
def test_parse_dinheiro(entrada, esperado):
    assert parse_dinheiro(entrada) == esperado


def test_parse_data():
    assert parse_data("15/10/2026 às 14:00") == datetime(2026, 10, 15, 14, 0)
    assert parse_data("2026-10-15T14:00:00.000Z") == datetime(2026, 10, 15, 14, 0)
    assert parse_data("Leilão em 15/10/2026 - 9h30") == datetime(2026, 10, 15, 9, 30)
    assert parse_data("amanhã") is None


def test_extrair_anos_e_local():
    assert extrair_anos("GOL 1.0 2015/2016") == (2015, 2016)
    assert extrair_anos("HONDA/PCX 160, 25/26, PLACA: T__-___7") == (2025, 2026)
    assert extrair_anos("FUSCA, 81/82, AZUL") == (1981, 1982)
    assert extrair_anos("lote 30/09 sem ano") == (None, None)
    assert extrair_anos("CG 160 2021") == (2021, 2021)
    assert separar_cidade_uf("Campinas/SP") == ("Campinas", "SP")
    assert separar_cidade_uf("belo horizonte - mg") == ("Belo Horizonte", "MG")


def test_normalizar_condicao():
    assert normalizar_condicao("Recuperado de financiamento") == "recuperado_financiamento"
    assert normalizar_condicao("Sinistro - indenizado") == "sinistro"
    assert normalizar_condicao("Sucata aproveitável") == "sucata"
    assert normalizar_condicao("FINANCEIRA") == "recuperado_financiamento"
    assert normalizar_condicao("seguro 0 km") == "sinistro"
    assert normalizar_condicao("sem sinistro") is None


def test_modelo_sem_detalhes_e_cidade_sem_informacao():
    lote = normalizar_lote(Lote(fonte="x", id_externo="1", cidade="Sem Informação, SI",
                                titulo="HONDA/CB300F TWISTER ABS, 25/25, PLACA: T__-___2, GASOL/ALC"))
    assert (lote.marca, lote.modelo, lote.ano_modelo, lote.categoria) == ("Honda", "CB300F TWISTER ABS", 2025, "moto")
    assert lote.cidade is None


def test_normalizar_lote_completo():
    lote = normalizar_lote(Lote(
        fonte="x", id_externo="1", titulo="VW/GOL 1.0 MI 2015/2016",
        descricao="Sinistro. Média monta.", cidade="Campinas/SP", combustivel="FLEX",
    ))
    assert (lote.marca, lote.modelo) == ("Volkswagen", "GOL 1.0 MI")
    assert (lote.ano_fabricacao, lote.ano_modelo) == (2015, 2016)
    assert lote.categoria == "carro"
    assert lote.monta == "media"
    assert lote.condicao == "sinistro"
    assert (lote.cidade, lote.uf) == ("Campinas", "SP")
    assert lote.combustivel == "flex"


def test_sucata_sem_monta_informada_vira_grande():
    lote = normalizar_lote(Lote(fonte="x", id_externo="1", titulo="FIAT/UNO 2010 - sucata"))
    assert lote.monta == "grande"
