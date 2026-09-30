"""Linha de comando: coletar, buscar, resumir leilões e subir a interface web."""

from __future__ import annotations

import argparse
import logging
import sys

from .banco import CAMINHO_PADRAO, ORDENACOES, Banco, Filtros
from .coletor import coletar
from .fontes import CONFIG_PADRAO, carregar_fontes


def _lista(valor: str | None) -> list[str] | None:
    return [v.strip() for v in valor.split(",") if v.strip()] if valor else None


def _moeda(v) -> str:
    if v is None:
        return "-"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def cmd_coletar(args) -> int:
    banco = Banco(args.banco)
    fontes = carregar_fontes(args.config)
    if args.fonte:
        fontes = [f for f in fontes if f.id in args.fonte]
    relatorio = coletar(banco, fontes)
    for r in relatorio.resultados:
        status = f"ERRO: {r.erro}" if r.erro else f"{r.lotes} lotes"
        print(f"  {r.fonte:<25} {status}")
    print(f"Total: {relatorio.total} lotes")
    return 1 if any(r.erro for r in relatorio.resultados) else 0


def _filtros(args) -> Filtros:
    return Filtros(
        texto=args.texto,
        categoria=_lista(args.categoria),
        marca=_lista(args.marca),
        modelo=args.modelo,
        monta=_lista(args.monta),
        condicao=_lista(args.condicao),
        fonte=_lista(args.fonte),
        leilao=_lista(args.leilao),
        uf=_lista(args.uf),
        ano_min=args.ano_min,
        ano_max=args.ano_max,
        km_max=args.km_max,
        lance_max=args.lance_max,
        apenas_futuros=args.futuros,
    )


def cmd_buscar(args) -> int:
    banco = Banco(args.banco)
    r = banco.buscar(_filtros(args), ordem=args.ordem, limite=args.limite)
    print(f"{r['total']} lote(s) encontrado(s)\n")
    for l in r["lotes"]:
        ano = f"{l['ano_fabricacao']}/{l['ano_modelo']}" if l["ano_modelo"] else "-"
        data = l["data_leilao"][:16].replace("T", " ") if l["data_leilao"] else "sem data"
        lance = l["lance_atual"] or l["lance_inicial"]
        print(f"[{l['fonte']}] {l['titulo']}")
        print(f"    {l['marca'] or '-'} {l['modelo'] or ''} | {ano} | {l['categoria'] or '-'} | "
              f"monta: {l['monta'] or '-'} | {l['condicao'] or '-'}")
        print(f"    {l['cidade'] or '-'}/{l['uf'] or '-'} | leilão: {l['leilao'] or '-'} em {data} | "
              f"lance: {_moeda(lance)}")
        if l["url"]:
            print(f"    {l['url']}")
    return 0


def cmd_leiloes(args) -> int:
    banco = Banco(args.banco)
    for item in banco.resumo_leiloes(_filtros(args)):
        data = item["data_inicio"][:16].replace("T", " ") if item["data_inicio"] else "sem data"
        print(f"== {item['leilao']} ({item['fonte']}) - {data} - {item['total']} lote(s)")
        for chave in ("categoria", "monta", "marca"):
            partes = ", ".join(f"{k}: {v}" for k, v in item[chave].items())
            print(f"   {chave:<10} {partes}")
        print()
    return 0


def cmd_servir(args) -> int:
    import uvicorn

    from .web.app import criar_app

    uvicorn.run(criar_app(args.banco), host=args.host, port=args.porta)
    return 0


def cmd_diagnosticar(args) -> int:
    from pathlib import Path

    from .diagnostico import executar, sites_de_argumentos

    sites = sites_de_argumentos(args.sites)
    print(f"Abrindo {len(sites)} site(s) no navegador. Não feche a janela até terminar.\n")
    destino = executar(sites, Path(args.saida), oculto=args.oculto,
                       executavel=args.navegador, espera_ms=args.espera * 1000)
    print(f"\nPronto! Arquivo gerado: {destino.resolve()}")
    print("Envie esse arquivo na conversa para montar a configuração dos leiloeiros.")
    return 0


def _adicionar_filtros(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("filtros (listas separadas por vírgula)")
    g.add_argument("texto", nargs="?", help="texto livre (ex.: 'gol 1.0')")
    g.add_argument("--categoria", help="carro, moto, caminhao, utilitario, onibus, maquina")
    g.add_argument("--marca", help="montadora (ex.: vw,fiat,chevrolet)")
    g.add_argument("--modelo")
    g.add_argument("--monta", help="sem_monta, pequena, media, grande")
    g.add_argument("--condicao", help="sinistro, recuperado_financiamento, frota, sucata...")
    g.add_argument("--fonte", help="id do leiloeiro")
    g.add_argument("--leilao", help="nome exato do leilão (veja o comando leiloes)")
    g.add_argument("--uf")
    g.add_argument("--ano-min", type=int)
    g.add_argument("--ano-max", type=int)
    g.add_argument("--km-max", type=int)
    g.add_argument("--lance-max", type=float)
    g.add_argument("--futuros", action="store_true", help="apenas leilões que ainda vão acontecer")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="buscaleilao", description=__doc__)
    parser.add_argument("--banco", default=str(CAMINHO_PADRAO), help="arquivo SQLite")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("coletar", help="coleta os lotes das fontes configuradas")
    p.add_argument("--config", default=str(CONFIG_PADRAO))
    p.add_argument("--fonte", action="append", help="coletar só esta fonte (pode repetir)")
    p.set_defaults(func=cmd_coletar)

    p = sub.add_parser("buscar", help="busca lotes")
    _adicionar_filtros(p)
    p.add_argument("--ordem", choices=list(ORDENACOES), default="data")
    p.add_argument("--limite", type=int, default=20)
    p.set_defaults(func=cmd_buscar)

    p = sub.add_parser("leiloes", help="resumo do que tem em cada leilão")
    _adicionar_filtros(p)
    p.set_defaults(func=cmd_leiloes)

    p = sub.add_parser("servir", help="sobe a interface web e a API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=8000)
    p.set_defaults(func=cmd_servir)

    p = sub.add_parser("diagnosticar",
                       help="grava como os sites dos leiloeiros entregam os lotes (gera um .zip)")
    p.add_argument("sites", nargs="*",
                   help="nomes (copart, superbid, ...) ou URLs; sem nada, testa os leiloeiros conhecidos")
    p.add_argument("--saida", default="diagnostico_leiloes.zip")
    p.add_argument("--oculto", action="store_true", help="não mostrar a janela do navegador")
    p.add_argument("--navegador", help="caminho de um executável do Chrome/Chromium")
    p.add_argument("--espera", type=int, default=4, help="segundos esperando cada página carregar")
    p.set_defaults(func=cmd_diagnosticar)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
