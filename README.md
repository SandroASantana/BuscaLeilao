# BuscaLeilão

Busca unificada em leilões de veículos: coleta os lotes de vários leiloeiros,
padroniza os dados e permite filtrar por **categoria**, **montadora**,
**monta** (pequena / média / grande / sem monta), condição, ano, preço, local
e leilão, além de mostrar **o que tem disponível em cada leilão**.

## Como funciona

```
 sites dos leiloeiros ──► fontes (coleta) ──► normalização ──► SQLite ──► API + interface web / CLI
```

1. **Fontes** (`buscaleilao/fontes/`): cada leiloeiro é uma fonte descrita em
   `config/fontes.json`. Há três tipos prontos:
   - `html`: raspa páginas de listagem usando seletores CSS;
   - `json`: consome a API JSON que muitos sites usam por trás da página
     (mais estável que raspar HTML);
   - `arquivo`: importa lotes de um arquivo JSON local.

   Se um site precisar de algo específico (login, JavaScript pesado), escreva
   uma classe Python que herde de `Fonte` e registre com `@registrar`.
2. **Normalização** (`buscaleilao/normalizacao.py`): transforma o texto de cada
   site em valores padronizados — `"VW"`, `"VOLKSWAGEN"` → `Volkswagen`;
   `"MÉDIA MONTA"` → `media`; `"R$ 12.500,00"` → `12500.0`;
   `"GOL 1.0 2015/2016"` → ano 2015/2016; `"Campinas/SP"` → cidade + UF;
   deduz a categoria (carro, moto, caminhão, utilitário, ônibus, máquina) e a
   condição (sinistro, recuperado de financiamento, frota, apreendido, sucata...).
3. **Banco** (`buscaleilao/banco.py`): SQLite com busca, facetas (contagem por
   categoria/marca/monta/leilão) e resumo por leilão. Lotes que somem do site
   numa nova coleta são marcados como inativos.
4. **Interface**: página web com filtros laterais e aba "Por leilão", API REST
   (FastAPI, documentação automática em `/docs`) e linha de comando.

## Rodando

```bash
pip install -e ".[dev]"

# coleta as fontes ativas em config/fontes.json (vem com dados de demonstração fictícios)
python -m buscaleilao coletar

# busca pela linha de comando
python -m buscaleilao buscar --categoria carro --marca vw,fiat --monta pequena,media --ano-min 2018
python -m buscaleilao buscar "hilux" --uf SP --lance-max 60000 --ordem lance
python -m buscaleilao leiloes            # o que tem em cada leilão

# interface web em http://127.0.0.1:8000  (API em /docs)
python -m buscaleilao servir

pytest                                   # testes
```

### API

| Rota | O que faz |
|---|---|
| `GET /api/lotes` | busca paginada; filtros: `q`, `categoria`, `marca`, `modelo`, `monta`, `condicao`, `fonte`, `leilao`, `uf`, `cidade`, `combustivel`, `ano_min`, `ano_max`, `km_max`, `lance_min`, `lance_max`, `data_de`, `data_ate`, `futuros`; `ordem` = `data`, `lance`, `lance_desc`, `ano`, `km`, `marca` |
| `GET /api/facetas` | contagens por leiloeiro, leilão, categoria, marca, monta, condição, UF, combustível |
| `GET /api/leiloes` | resumo de cada leilão (total, categorias, montas, principais montadoras) |
| `GET /api/lotes/{fonte}/{id}` | detalhe de um lote |

Filtros de lista aceitam vários valores: `?categoria=carro&categoria=moto`.

## Adicionando um leiloeiro real

### Diagnóstico automático

O comando `diagnosticar` abre os sites num navegador (Edge ou Chrome já
instalados), entra nas páginas de veículos e grava num `.zip` o HTML e as
respostas das APIs que o site usa. Esse arquivo é a base para escrever a
configuração de cada leiloeiro.

```bash
pip install playwright
python -m buscaleilao diagnosticar                  # leiloeiros conhecidos
python -m buscaleilao diagnosticar copart superbid  # só alguns
python -m buscaleilao diagnosticar https://www.leiloeiro.com.br/veiculos
```

O navegador abre com perfil novo (sem seus logins ou cookies). O resultado é
`diagnostico_leiloes.zip`.

### Manualmente

1. Abra o site do leiloeiro com o DevTools (F12) na aba **Rede/Network** e
   navegue pela listagem de veículos. Se aparecer uma requisição que devolve
   JSON com os lotes, use o tipo `json`; senão, use o tipo `html`.
2. Copie um dos modelos desativados (`modelo_html` / `modelo_api`) em
   `config/fontes.json`, ajuste URL, seletores ou caminhos dos campos e mude
   `"ativo"` para `true`.
3. Rode `python -m buscaleilao -v coletar --fonte SEU_ID` e confira o resultado
   com `buscar --fonte SEU_ID`.
4. Agende a coleta (cron, por exemplo a cada hora) para manter os dados
   atualizados.

Cada site tem um layout próprio e muda com o tempo, então a configuração de
cada fonte precisa de manutenção quando o site é alterado. O coletor isola as
falhas: se um site quebrar, os outros continuam sendo coletados.

## Cuidados

- Verifique os **termos de uso** de cada site antes de coletar dados; alguns
  leiloeiros oferecem API ou parceria, o que é o caminho mais seguro.
- O cliente HTTP respeita o `robots.txt`, se identifica no User-Agent e espera
  um intervalo entre requisições (`intervalo` na configuração) para não
  sobrecarregar os sites.
- O sistema mostra o link do lote no site original; lance, edital e condições
  de pagamento devem sempre ser conferidos lá.
- `dados/exemplo_lotes.json` contém **dados fictícios** apenas para
  demonstração.
