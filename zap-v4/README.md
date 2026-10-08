# ZAP Imóveis v4 — coleta simplificada com maestro

O servidor Flask mantém uma fila central de tarefas. Cada tarefa representa exatamente:

```text
município com população < 100.000: uma busca de venda com 11 tipos selecionados
município com população >= 100.000 ou não informada: uma busca por tipo
```

Os workers não possuem mais listas ou grupos fixos. Quando ficam disponíveis, pedem a próxima tarefa ao servidor, percorrem a busca até o fim e informam o resultado.

## O que o maestro controla

- reserva exclusiva para impedir dois workers na mesma tarefa;
- retomada de uma reserva pelo mesmo worker;
- liberação automática de reservas expiradas;
- tentativas com intervalo crescente para erros temporários;
- estados separados para conclusão, ausência de anúncios, página inexistente e erro permanente;
- encerramento real quando não existem tarefas pendentes ou ativas;
- persistência da fila em `dados/fila_maestro.sqlite3`.

## Preparar a lista nacional de municípios

Use um CSV com as colunas `municipio` e `uf`. As colunas `url`, `prioridade` e `populacao` (inteiro sem separador de milhar) são opcionais.

```powershell
python .\scripts\preparar_municipios.py "CAMINHO\municipios_do_brasil.csv"
```

O comando cria `config/municipios.csv`. Um arquivo pequeno de referência está em `config/municipios.exemplo.csv`.

Os tipos das buscas separadas ficam em `config/tipos_imovel.json`. O campo opcional `rota` permite usar caminhos específicos do site, como `quitinetes`. A busca única usa os 11 filtros do link fornecido: apartamento, studio, casa, condomínio, casa de vila, cobertura, flat, loft, lote/terreno, sobrado e kitnet.

## Rodar somente SP com o Censo 2022

O `config/municipios.csv` foi preparado com os 645 municípios da planilha `populacao_censitaria2022_tabela.xlsx`, usando a coluna de 2022. Para regenerar, instale `openpyxl` e execute `python .\scripts\preparar_sp_censo2022.py "CAMINHO/populacao_censitaria2022_tabela.xlsx"`.

Na pasta `zap-v4`, inicie uma fila específica para esta regra:

```powershell
python -m pip install -r .\server\requirements.txt
$env:ZAP_FILA_DB = "$PWD\dados\fila_sp_censo2022.sqlite3"
python .\server\server.py
```

Em outro terminal, prepare a fila:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/maestro/preparar -ContentType application/json -Body '{}'
Invoke-RestMethod http://127.0.0.1:5000/maestro/status
```

Pare o servidor anterior antes de iniciar este. Use um banco novo se já houver tarefas preparadas pela regra antiga: importar novamente não remove tarefas existentes. Prepare os workers conforme abaixo, carregue as extensões nos perfis e inicie a coleta pelo popup.

## Criar a fila

Inicie o servidor:

```powershell
python -m pip install -r .\server\requirements.txt
python .\server\server.py
```

Depois crie somente as tarefas ainda inexistentes:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/maestro/preparar -ContentType application/json -Body '{}'
```

O banco usa uma chave única para `UF + município + tipo`. Executar a preparação novamente não duplica tarefas.

Para consultar o andamento:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/maestro/status
```

## Preparar os workers

```powershell
.\preparar_workers.ps1
```

Carregue cada pasta em um perfil separado do Chrome ou Edge:

```text
workers/worker1/extensao
workers/worker2/extensao
workers/worker3/extensao
```

Os três workers são genéricos. O maestro pode entregar qualquer município e tipo disponível.

## Regras contra loops e falsos resultados

- A mensagem `Nenhum imóvel encontrado com esses filtros` conclui a tarefa como `SEM_ANUNCIOS`.
- Links do carrossel `Mais opções para você na mesma região` são ignorados.
- Cards com `data-testid="recommendation-item-..."` ou URL com `source=showcase,rp` são ignorados.
- A página 404 conclui a tarefa como `PAGINA_NAO_ENCONTRADA`.
- Cloudflare e erros 5xx geram recargas limitadas. Depois disso, o maestro agenda nova tentativa ou marca erro permanente.
- A repetição dos mesmos anúncios em páginas consecutivas encerra a paginação.
- Uma página já concluída não é processada novamente.
- Sem um link real de próxima página, a tarefa termina. O coletor não inventa páginas adicionais.
- Quando a fila termina, o servidor responde `fila_concluida` e o worker para.

## Saídas

A coleta agora salva os anúncios incrementalmente em `dados/cards_zap_v4.sqlite3` (ou na pasta indicada por `ZAP_DADOS_DIR`). Na primeira inicialização, o servidor importa o JSON antigo uma única vez, em uma transação, preservando o arquivo original. Espere a importação terminar antes de retomar os workers. O banco da fila e os checkpoints continuam sendo usados sem reset.

O JSON e o CSV antigos não são mais regravados a cada página. Para atualizar o CSV consolidado, execute:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5000/exportar-csv
```

O botão de Excel continua exportando os dados atuais, agora lendo do SQLite. A rolagem automática foi removida: o coletor usa os cards presentes após a espera de carregamento. Fotos carregadas somente com rolagem podem não ser capturadas.

- `dados/cards_zap_v4.sqlite3`: anúncios atuais, deduplicados por ID ou URL;
- `dados/cards_zap_v4.json`: arquivo legado preservado;
- `dados/cards_zap_v4.csv`: cópia tabular atualizada sob demanda;
- `dados/incidentes_zap_v4.csv`: erros com tarefa, município, tipo, página e horário;
- `dados/fila_maestro.sqlite3`: estado persistente do maestro;
- `dados/zap_v4_coleta_nacional.xlsx`: exportação consolidada;
- `workers/workerN/checkpoint.json`: checkpoint local de cada worker.

## Variáveis opcionais

```text
ZAP_MUNICIPIOS_CSV   caminho do CSV de municípios
ZAP_TIPOS_JSON       caminho do JSON de tipos
ZAP_FILA_DB          caminho do banco SQLite
ZAP_LEASE_SEGUNDOS   duração da reserva de uma tarefa, padrão 900
```
