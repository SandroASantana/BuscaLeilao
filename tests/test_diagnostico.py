import json
import zipfile

import pytest

from buscaleilao.diagnostico import (
    SITES_PADRAO, Pagina, RespostaJson, ResultadoSite, escolher_links, salvar_zip,
    sites_de_argumentos,
)


def test_escolher_links_prefere_veiculos_do_mesmo_site():
    links = [
        ("/login", "Entrar"),
        ("/imoveis", "Imóveis"),
        ("/leiloes", "Próximos leilões"),
        ("/veiculos?categoria=carros", "Carros"),
        ("/veiculos?categoria=carros#topo", "Carros"),
        ("https://leilao.exemplo.com.br/lotes", "Lotes"),
        ("https://outro.com.br/veiculos", "Veículos em outro site"),
        ("javascript:void(0)", "Veículos"),
        ("/", "Início"),
    ]
    escolhidos = escolher_links("https://www.exemplo.com.br/", links, limite=3)
    assert escolhidos[0] == "https://www.exemplo.com.br/veiculos?categoria=carros"
    assert "https://leilao.exemplo.com.br/lotes" in escolhidos
    assert "https://www.exemplo.com.br/leiloes" in escolhidos
    assert not any("login" in u or "imoveis" in u or "outro.com.br" in u for u in escolhidos)


def test_sites_de_argumentos():
    assert sites_de_argumentos([]) == SITES_PADRAO
    assert sites_de_argumentos(["copart", "https://www.leiloeiro-x.com.br/veiculos"]) == {
        "copart": SITES_PADRAO["copart"],
        "leiloeiro_x_com_br": "https://www.leiloeiro-x.com.br/veiculos",
    }
    with pytest.raises(SystemExit):
        sites_de_argumentos(["nao_existe"])


def test_salvar_zip(tmp_path):
    res = ResultadoSite("teste", "https://t.com.br/", paginas=[
        Pagina("https://t.com.br/", "Início", "<html></html>"),
        Pagina("https://t.com.br/veiculos", erro="Timeout"),
    ], respostas=[RespostaJson("https://api.t.com.br/lotes?p=1", "POST", 200, '{"p":1}', '{"itens":[]}')])
    destino = salvar_zip([res], tmp_path / "d.zip")
    with zipfile.ZipFile(destino) as z:
        nomes = z.namelist()
        resumo = z.read("teste/resumo.txt").decode()
        api = json.loads(z.read([n for n in nomes if n.startswith("teste/api/")][0]))
    assert len([n for n in nomes if n.startswith("teste/paginas/")]) == 1
    assert "ERRO Timeout" in resumo and "POST 200" in resumo
    assert api["corpo_requisicao"] == '{"p":1}'
