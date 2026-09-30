import json
from pathlib import Path

from buscaleilao.banco import Banco, Filtros
from buscaleilao.coletor import coletar
from buscaleilao.fontes import Fonte, FonteApiJson, FonteHtml, carregar_fontes, criar_fonte
from buscaleilao.fontes.api_json import pegar
from buscaleilao.normalizacao import normalizar_lote

FIXTURES = Path(__file__).parent / "fixtures"
RAIZ = Path(__file__).parent.parent


class RespostaFalsa:
    def __init__(self, texto="", dados=None):
        self.text = texto
        self._dados = dados

    def json(self):
        return self._dados


class ClienteFalso:
    """Substitui o acesso à rede: devolve respostas pré-definidas por página."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.urls = []

    def requisitar(self, url, metodo="GET", **kwargs):
        self.urls.append((metodo, url, kwargs))
        return self.respostas.pop(0) if self.respostas else RespostaFalsa("", {"itens": []})


CONFIG_HTML = {
    "id": "html1",
    "url": "https://leiloeiro.test/veiculos?p={pagina}",
    "paginas": 3,
    "seletores": {
        "item": "div.lote", "id_externo": "@data-id", "titulo": ".lote-titulo", "url": "a@href",
        "lance_atual": ".lote-lance", "data_leilao": ".lote-data", "cidade": ".lote-local",
        "monta": ".lote-monta", "imagem_url": "img@src",
    },
    "constantes": {"leilao": "Leilão Teste"},
}


def test_fonte_html_extrai_e_para_na_pagina_vazia():
    html = (FIXTURES / "listagem.html").read_text()
    cliente = ClienteFalso([RespostaFalsa(html), RespostaFalsa("<html></html>")])
    fonte = FonteHtml(cliente=cliente, **CONFIG_HTML)
    lotes = [normalizar_lote(l) for l in fonte.coletar()]

    assert len(cliente.urls) == 2  # parou ao encontrar a página 2 vazia
    assert [l.id_externo for l in lotes] == ["A1", "A2"]
    gol, cg = lotes
    assert gol.url == "https://leiloeiro.test/lote/A1"
    assert gol.imagem_url == "https://leiloeiro.test/fotos/a1.jpg"
    assert (gol.marca, gol.ano_modelo, gol.monta, gol.lance_atual) == ("Volkswagen", 2019, "pequena", 21300.0)
    assert (gol.cidade, gol.uf, gol.leilao) == ("Sorocaba", "SP", "Leilão Teste")
    assert gol.data_leilao.isoformat() == "2026-10-15T14:00:00"
    assert (cg.marca, cg.categoria, cg.imagem_url) == ("Honda", "moto", None)


def test_fonte_html_nao_repete_lotes_de_paginas_repetidas():
    html = (FIXTURES / "listagem.html").read_text()
    # alguns sites devolvem a última página para qualquer número acima do máximo
    cliente = ClienteFalso([RespostaFalsa(html), RespostaFalsa(html), RespostaFalsa(html)])
    lotes = list(FonteHtml(cliente=cliente, **CONFIG_HTML).coletar())
    assert len(lotes) == 2
    assert len(cliente.urls) == 2


def test_pegar_caminho():
    dados = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert pegar(dados, "a.b.1.c") == 2
    assert pegar(dados, "a.x.c") is None
    assert pegar(dados, "a.b.5.c") is None


def test_fonte_api_json():
    pagina1 = {"dados": {"itens": [
        {"id": 10, "descricao": "Caminhão Scania R 450 2019/2020",
         "veiculo": {"marca": "SCANIA", "anoModelo": 2020, "tipo": "Caminhões", "monta": "MEDIA"},
         "lanceAtual": 250000.5, "leilao": {"titulo": "Pesados #3", "data": "2026-11-02T10:00:00Z"},
         "fotos": [{"url": "https://cdn.test/10.jpg"}]},
        {"id": 11, "descricao": "Moto Honda Biz 125 2022",
         "veiculo": {"marca": "honda", "anoModelo": "2022"}, "lanceAtual": "R$ 6.100,00",
         "leilao": {"titulo": "Pesados #3"}, "fotos": []},
    ]}}
    config = {
        "id": "api1", "url": "https://api.test/lotes?page={pagina}", "paginas": 5,
        "caminho_lista": "dados.itens",
        "campos": {"id_externo": "id", "titulo": "descricao", "marca": "veiculo.marca",
                   "ano_modelo": "veiculo.anoModelo", "categoria": "veiculo.tipo",
                   "monta": "veiculo.monta", "lance_atual": "lanceAtual",
                   "leilao": "leilao.titulo", "data_leilao": "leilao.data", "imagem_url": "fotos.0.url"},
        "url_lote": "https://www.test/lote/{id_externo}",
    }
    cliente = ClienteFalso([RespostaFalsa(dados=pagina1)])
    lotes = [normalizar_lote(l) for l in FonteApiJson(cliente=cliente, **config).coletar()]
    scania, biz = lotes
    assert (scania.id_externo, scania.marca, scania.categoria, scania.monta) == ("10", "Scania", "caminhao", "media")
    assert scania.url == "https://www.test/lote/10"
    assert scania.lance_atual == 250000.5
    assert scania.imagem_url == "https://cdn.test/10.jpg"
    assert (biz.marca, biz.categoria, biz.ano_modelo, biz.lance_atual) == ("Honda", "moto", 2022, 6100.0)


def test_corpo_post_com_pagina():
    config = {"id": "api2", "url": "https://api.test/busca", "metodo": "POST", "paginas": 2,
              "corpo": {"page": "{pagina}", "filtro": "veiculos-{pagina}"},
              "caminho_lista": "itens", "campos": {"id_externo": "id", "titulo": "t"}}
    cliente = ClienteFalso([RespostaFalsa(dados={"itens": [{"id": 1, "t": "FIAT/UNO 2010"}]})])
    list(FonteApiJson(cliente=cliente, **config).coletar())
    assert cliente.urls[0][2]["json"] == {"page": 1, "filtro": "veiculos-1"}
    assert cliente.urls[1][2]["json"] == {"page": 2, "filtro": "veiculos-2"}


class FonteQuebrada(Fonte):
    tipo = "quebrada"

    def coletar(self, max_paginas=None):
        raise RuntimeError("site fora do ar")


def test_coletor_isola_falhas(tmp_path, monkeypatch):
    monkeypatch.chdir(RAIZ)
    banco = Banco(tmp_path / "t.db")
    demo = criar_fonte({"id": "demo", "tipo": "arquivo", "nome": "Demo", "caminho": "dados/exemplo_lotes.json"})
    relatorio = coletar(banco, [FonteQuebrada("ruim"), demo])
    assert relatorio.resultados[0].erro == "RuntimeError: site fora do ar"
    assert relatorio.resultados[1].lotes == 60
    assert banco.buscar(Filtros(fonte=["demo"]))["total"] == 60


def test_config_padrao_carrega(monkeypatch):
    monkeypatch.chdir(RAIZ)
    fontes = carregar_fontes()
    assert [f.id for f in fontes] == ["sodre_santoro", "freitas", "mega_leiloes", "copart"]
    todos = json.loads((RAIZ / "config/fontes.json").read_text())["fontes"]
    for config in todos:  # as desativadas também precisam ser válidas
        criar_fonte({k: v for k, v in config.items() if k != "ativo"})


def test_extrair_com_regex():
    from bs4 import BeautifulSoup

    from buscaleilao.fontes.html import extrair

    item = BeautifulSoup('<div><a href="/L?leilaoId=8&amp;loteNumero=12">x</a><b>Lote 7</b></div>',
                         "html.parser").div
    assert extrair(item, "a@href|re:leilaoId=(\\d+)&loteNumero=(\\d+)") == "8-12"
    assert extrair(item, "b|re:\\d+") == "7"
    assert extrair(item, "b|re:nada") is None


def test_montar_lote_formatos_e_exclusao():
    from buscaleilao.fontes import montar_lote

    config = {
        "constantes": {"categoria": "carro"},
        "formatos": {"url": "https://s/{_leilao}/{id_externo}", "leilao": "Leilão {_leilao} {_falta}"},
        "excluir": {"_status": "vendido"},
    }
    lote = montar_lote("f", {"id_externo": "9", "titulo": "UNO", "_leilao": "77"}, config)
    assert lote.url == "https://s/77/9"
    assert lote.leilao is None  # formato com campo ausente é ignorado
    assert lote.categoria == "carro"
    assert montar_lote("f", {"id_externo": "9", "titulo": "UNO", "_status": "VENDIDO"}, config) is None


def test_fonte_html_varias_urls():
    html = (FIXTURES / "listagem.html").read_text()
    cliente = ClienteFalso([RespostaFalsa(html), RespostaFalsa(html.replace("A1", "B1").replace("A2", "B2"))])
    config = {**CONFIG_HTML, "paginas": 1}
    config.pop("url")
    config["urls"] = ["https://leiloeiro.test/carros", "https://leiloeiro.test/motos"]
    lotes = list(FonteHtml(cliente=cliente, **config).coletar())
    assert [l.id_externo for l in lotes] == ["A1", "A2", "B1", "B2"]
    assert [u for _, u, _ in cliente.urls] == config["urls"]


def test_api_paginacao_por_deslocamento_e_formulario():
    def pagina(ids):
        return RespostaFalsa(dados={"itens": [{"id": i, "t": f"FIAT/UNO {i}"} for i in ids]})

    config = {"id": "api3", "url": "https://api.test/busca?p={pagina0}", "metodo": "POST", "paginas": 9,
              "tamanho_pagina": 2, "corpo_form": "start={deslocamento}&length=2",
              "caminho_lista": "itens", "campos": {"id_externo": "id", "titulo": "t"}}
    cliente = ClienteFalso([pagina([1, 2]), pagina([3, 4]), pagina([5])])
    lotes = list(FonteApiJson(cliente=cliente, **config).coletar())
    assert len(lotes) == 5
    assert [(u, kw["data"]) for _, u, kw in cliente.urls[:3]] == [
        ("https://api.test/busca?p=0", "start=0&length=2"),
        ("https://api.test/busca?p=1", "start=2&length=2"),
        ("https://api.test/busca?p=2", "start=4&length=2"),
    ]
    # max_paginas limita a coleta
    cliente = ClienteFalso([pagina([1, 2]), pagina([3, 4]), pagina([5])])
    assert len(list(FonteApiJson(cliente=cliente, **config).coletar(max_paginas=1))) == 2


def test_testar_gera_relatorio(tmp_path):
    import zipfile

    from buscaleilao.teste_fontes import testar

    html = (FIXTURES / "listagem.html").read_text()
    ok = FonteHtml(cliente=ClienteFalso([RespostaFalsa(html)]), **{**CONFIG_HTML, "paginas": 1})
    banco = Banco(tmp_path / "t.db")
    destino = testar(banco, [ok, FonteQuebrada("ruim")], tmp_path / "r.zip", log=lambda *_: None)
    with zipfile.ZipFile(destino) as z:
        resumo = z.read("resumo.txt").decode()
        resposta = json.loads(z.read("html1/resposta_0.json"))
        assert "ruim/erro.txt" in z.namelist()
    assert "== html1: 2 lote(s) - ok" in resumo
    assert "== ruim: 0 lote(s) - ERRO RuntimeError: site fora do ar" in resumo
    assert "VW/GOL" in resposta["resposta"]
    assert banco.buscar(Filtros(fonte=["html1"]))["total"] == 2
