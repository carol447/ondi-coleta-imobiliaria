# ONDI — Coleta imobiliária

Projeto de engenharia de dados para coleta e organização de anúncios imobiliários, com extensões JavaScript, API Python/Flask, execução paralela e armazenamento SQLite.

## Versão principal para execução

A versão com fila central, maestro e armazenamento incremental fica em `zap-v4/`. A raiz preserva a implementação v3 para comparação da evolução arquitetural.

```powershell
cd zap-v4
python -m pip install -r server/requirements.txt
Copy-Item config/municipios.exemplo.csv config/municipios.csv
.\preparar_workers.ps1
python server/server.py
```

Em outro terminal, na pasta `zap-v4`, prepare a fila:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/maestro/preparar -ContentType application/json -Body '{}'
```

Carregue as extensões em perfis separados do Chrome e inicie a coleta pelos popups. Consulte `zap-v4/README.md` para configuração e limites. A lista de exemplo é pequena; a versão de portfólio não inclui bases coletadas nem listas operacionais. Na v3, forneça `codigos_municipios_regioes.csv` ou suas listas de municípios antes da execução.

## Verificação

```bash
cd zap-v4
python -m unittest discover -s tests -v
```

O exemplo de Telegram não contém credenciais. Configure localmente `server/telegram_config.json` se desejar os avisos. Respeite as condições de acesso da fonte e os limites da coleta.

## Documentação da versão v3

# ZAP Imóveis — coletor com múltiplos workers

Projeto de coleta de anúncios de venda do ZAP Imóveis com uma extensão JavaScript no Chrome e um servidor Python/Flask. A extensão percorre as listagens, abre os anúncios e envia os dados ao servidor, que salva os resultados por município e worker.

## Versões nesta pasta

- **Raiz do projeto (v3):** três workers com listas próprias de municípios, coleta de listagem e detalhes, arquivos separados por município. Os comandos abaixo se referem a esta versão.
- **`zap-v4/`:** versão com maestro, fila central em SQLite e tarefas por município e tipo de imóvel. Consulte o [README da v4](zap-v4/README.md) para executá-la.

As duas versões usam a porta `5000` por padrão. Execute apenas um dos servidores por vez.

## Como funciona

1. O servidor lê a lista de municípios de cada worker.
2. A extensão solicita o município a processar e abre sua busca no ZAP.
3. Em cada página, coleta os cards e visita os links dos anúncios para extrair os detalhes.
4. O servidor registra os dados, filtra URLs de detalhes já salvas e mantém um checkpoint por worker.
5. Ao terminar o município, o worker segue para o próximo item de sua lista.

A navegação acontece no navegador pela extensão; não há dependência de Selenium, Playwright ou Puppeteer. Os workers disponíveis são `worker1`, `worker2` e `worker3`, cada um com perfil de navegador, lista, checkpoint e log próprios.

## Requisitos

- Python 3.10 ou superior recomendado.
- Google Chrome com permissão para carregar extensões descompactadas.
- PowerShell para executar o script de preparação no Windows.
- Conexão com a internet e acesso ao ZAP Imóveis.

Dependências Python: `flask`, `flask-cors` e `openpyxl`, declaradas em `server/requirements.txt`.

## Instalação e execução

Execute os comandos a partir da raiz do projeto.

### 1. Instalar as dependências

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\server\requirements.txt
```

Os comandos usam diretamente o Python do ambiente virtual, sem precisar ativá-lo.

### 2. Conferir as listas de municípios

As listas usadas normalmente ficam em:

```text
workers/worker1/municipios.csv
workers/worker2/municipios.csv
workers/worker3/municipios.csv
```

Se já houver listas e uma coleta em andamento, preserve esses arquivos. Para gerar novamente a distribuição a partir de `codigos_municipios_regioes.csv`:

```powershell
.\.venv\Scripts\python.exe .\scripts\gerar_workers_municipios.py
```

Esse comando **sobrescreve as três listas**. O script lê a fonte em Windows-1252, filtra os registros que não representam municípios e distribui os municípios entre os workers considerando a região administrativa e o tamanho das listas. Os CSVs gerados usam ponto e vírgula e UTF-8 com BOM.

Formato aceito, com exemplo de coordenadas opcionais:

```csv
municipio;estado;url;latitude;longitude;cod_ibge;regiao_administrativa;regiao_metropolitana;drs
Presidente Prudente;SP;;-22.120594;-51.387408;3541406;RA Presidente Prudente;Demais municipios;DRS Presidente Prudente
```

Quando `url` fica vazia, o servidor monta a busca de venda do município. As coordenadas, quando preenchidas, entram no parâmetro `onde`. A busca padrão inclui múltiplos tipos residenciais e terrenos.

**Prioridade de leitura:** se existir `worker1.csv`, `worker2.csv` ou `worker3.csv` na raiz, esse arquivo substitui a respectiva lista em `workers/`.

### 3. Preparar as extensões

```powershell
.\preparar_workers.ps1
```

O script copia `extensao/` para cada worker e define seu identificador em `worker_config.js`. Ele substitui as cópias existentes das extensões, mas preserva as listas de municípios já criadas.

No Chrome:

1. Crie um perfil separado para cada worker que for utilizar.
2. Abra `chrome://extensions/` e ative o **Modo do desenvolvedor**.
3. Clique em **Carregar sem compactação**.
4. Selecione a pasta correspondente ao perfil:

```text
workers/worker1/extensao
workers/worker2/extensao
workers/worker3/extensao
```

Use uma extensão de worker por perfil e uma aba de coleta por worker.

### 4. Iniciar o servidor

```powershell
.\.venv\Scripts\python.exe .\server\server.py
```

Mantenha o terminal aberto. O servidor escuta em `http://127.0.0.1:5000`.

### 5. Iniciar a coleta

Em cada perfil, abra uma página de listagem do ZAP Imóveis, abra o popup da extensão e clique em **Iniciar coleta**. O servidor fornece o município da lista do worker.

O popup permite:

| Controle | Função |
| --- | --- |
| Iniciar coleta | Inicia a execução do worker. |
| Parar | Solicita a pausa e salva o estado. |
| Resetar progresso | Reinicializa o estado local da extensão; não equivale a apagar os dados e checkpoints do servidor. |
| Gerar Excel final | Exporta os CSVs do município atual do worker para Excel. |

O status apresenta município, página, fila de anúncios, detalhes salvos, tempos, municípios concluídos e estimativa de término. Abra novamente o popup para consultar os valores atualizados.

## Dados coletados e saídas

A listagem registra URL, página, preço, metragem, quartos, localização e descrição. Os detalhes acrescentam tipo de imóvel, anunciante e data do anúncio, quando disponíveis. Os registros incluem worker, município, estado e data/hora da coleta.

Os campos dependem do conteúdo disponível na página e podem ficar vazios.

```text
Estados/<UF>/<municipio>/dados/
├── urls_zap_worker1.csv
├── imoveis_zap_detalhes_worker1.csv
├── dados_zap_<municipio>_worker1.xlsx
└── bruto/
    └── dados_worker1.json
```

O sufixo muda conforme o worker. O arquivo em `bruto/` contém um objeto JSON por linha (JSON Lines), apesar da extensão `.json`. O Excel é criado quando a exportação é solicitada e contém as abas `Anuncios_Detalhes` e `URLs_Listagem`.

Arquivos de acompanhamento:

| Caminho | Conteúdo |
| --- | --- |
| `workers/workerN/checkpoint.json` | Progresso persistido no servidor. |
| `workers/workerN/workerN.log` | Eventos e erros do worker. |
| `workers/municipios_sem_imoveis.csv` | Municípios identificados sem anúncios. |
| `workers/municipios_url_invalida.csv` | Municípios com URL inválida para revisão posterior. |

## Consultar o andamento e exportar

Consultar um worker no PowerShell:

```powershell
Invoke-RestMethod 'http://127.0.0.1:5000/status?worker=worker1'
```

Consultar seu checkpoint:

```powershell
Invoke-RestMethod 'http://127.0.0.1:5000/worker/worker1/checkpoint'
```

Exportar um município específico, inclusive depois de o worker avançar para outro:

```powershell
$corpo = @{ worker = 'worker1'; municipio = 'Presidente Prudente'; estado = 'SP' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5000/exportar-excel' -ContentType 'application/json' -Body $corpo
```

Gerar um relatório dos dados já coletados:

```powershell
.\.venv\Scripts\python.exe .\scripts\relatorio_coleta_v3.py --csv .\relatorio_coleta_v3_por_municipio.csv
```

## Limites e recuperação

- A coleta limita a paginação a **50 páginas por município** e também termina quando não encontra próxima página ou anúncios.
- A configuração da extensão contém um limite de **10.000 detalhes** e intervalos entre ações. Consulte `CONFIG` em `extensao/content.js`.
- Páginas incompletas podem receber até **três recargas** antes de a execução pausar.
- Verificação humana/Cloudflare pausa a execução e gera aviso; resolva a verificação no navegador antes de iniciar novamente.
- Municípios sem anúncios ou com URL inválida são registrados para acompanhamento e o worker segue a lista.
- O progresso fica no checkpoint do servidor e no armazenamento local do navegador. Preserve ambos e mantenha o mesmo perfil para continuar uma coleta.
- A filtragem de detalhes já salvos usa URLs por município e worker; não representa uma deduplicação global entre todos os workers.

A coleta depende da estrutura das páginas do ZAP. Alterações no site podem exigir ajustes nos seletores da extensão. O limite de páginas e os campos indisponíveis também restringem a cobertura dos resultados.

## Problemas comuns

| Sintoma | O que verificar |
| --- | --- |
| Extensão não se comunica com o servidor | Confirme que `server/server.py` está rodando e consulte o endpoint `/status?worker=worker1`. |
| Popup informa que a página não respondeu | Abra uma página do ZAP, recarregue a extensão em `chrome://extensions/` e atualize a página com F5. |
| Dois perfis aparecem como o mesmo worker | Confira a pasta carregada em cada perfil e seu `worker_config.js`. |
| Alterações em `extensao/` não aparecem | Execute novamente `preparar_workers.ps1`, recarregue as extensões e atualize as abas. |
| Excel não pode ser salvo | Feche o arquivo no Excel e solicite a exportação novamente. |
| Exportação informa que não há município atual | Use a requisição de exportação com `municipio`, `estado` e `worker` explícitos. |
| Porta 5000 ocupada | Verifique se outro servidor, inclusive o da v4, já está em execução. |

## Estrutura principal

```text
extensao/                       Extensão-base: coleta, popup e comunicação
server/server.py                API Flask e coordenação dos workers
server/excel_utils.py           Exportação e formatação do Excel
server/requirements.txt         Dependências Python
scripts/gerar_workers_municipios.py
                                Distribuição das listas de municípios
scripts/relatorio_coleta_v3.py   Relatório da coleta existente
preparar_workers.ps1             Preparação das extensões dos três workers
codigos_municipios_regioes.csv   Fonte para geração das listas
workers/                        Listas, extensões, checkpoints e logs
Estados/                        Resultados por UF e município
zap-v4/                         Versão separada com fila central e maestro
```

`server/gerar_excel.py` é um utilitário com caminhos fixos para arquivos legados de São Paulo. Para os arquivos atuais com sufixo do worker, utilize o popup ou `/exportar-excel`.
