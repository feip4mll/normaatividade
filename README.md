# NORMA - Atividade 04 / Message Broker

Loja de móveis com frontend HTML/CSS/JS, API Python/Flask e workers independentes com RabbitMQ real. Nenhum pagamento ou e-mail real é realizado.

## Iniciar com Docker

Pré-requisito: Docker Desktop com engine Linux em execução. Se acabou de instalar WSL/Virtual Machine Platform no Windows, reinicie o computador antes. Não execute RabbitMQ nativo e Docker na mesma porta simultaneamente.

Na pasta deste README:

```powershell
docker compose up -d --build
docker compose ps
```

- Loja: http://localhost:8000
- Laboratório para rajada e consulta de eventos: http://localhost:8000/demo.html
- RabbitMQ Management: http://localhost:15672
- Usuário: `norma`; senha local de demonstração: `norma-local-demo`.
- Portas publicadas somente em loopback. Este projeto é um laboratório local, sem autenticação de clientes.

## Estrutura

```text
frontend/             loja, checkout integrado e laboratório
api/app.py            validação, POST de pedidos, GET de status, HTTP 202
workers/worker.py     payment / inventory / notifications
common.py             exchanges, bindings, persistência e outbox
tests/                testes de regras e integração com broker real
evidencias/           resultados e logs de execução, quando coletados
compose.yaml          broker, API e workers
requirements.txt      dependências Python
```

## Arquitetura

```text
Loja --POST /api/orders--> API --pedido.criado--> norma.events (topic)
                            |                       |             |
                            +--HTTP 202              v             v
                                               norma.payment  norma.notifications
                                                    |
                              pagamento.aprovado <--+--> pagamento.recusado
                                      |                         |
                                norma.inventory          notifications
                                      |
                                estoque.reservado --> notifications

Rejeição manual em qualquer fila: NACK(requeue=False)
  --> norma.dlx (direct), routing key erro --> norma.dlq
```

| Exchange | Fila | Binding | Consumidor |
|---|---|---|---|
| norma.events / topic | norma.payment | pedido.criado | payment |
| norma.events / topic | norma.inventory | pagamento.aprovado | inventory |
| norma.events / topic | norma.notifications | pedido.*, pagamento.*, estoque.* | notifications |
| norma.dlx / direct | norma.dlq | erro | inspeção manual |

O mesmo `pedido.criado` chega a payment e notifications. A coreografia segue com `pagamento.aprovado`, que aciona inventory. O serviço de estoque registra uma reserva fictícia; não há ERP nem catálogo de disponibilidade real.

## Roteiro dos testes no vídeo

### 1. Compra normal

Abra a loja, adicione produto, preencha dados fictícios e escolha Pix ou cartão de teste. Envie. Mostre `HTTP 202` e o estado em processamento, depois pagamento aprovado e reserva de estoque. Mostre os logs:

```powershell
docker compose logs -f payment inventory notifications
```

O atraso de 3 segundos no payment torna o desacoplamento visível. A API aguarda a confirmação de publicação do broker, mas nunca aguarda a conclusão dos workers.

### 2. Queda do serviço

```powershell
docker compose stop payment
```

No laboratório web envie 3 pedidos. No Management abra Queues and Streams > norma.payment: consumidores devem estar em 0 e Ready deve aumentar. O restante da aplicação continua atendendo.

```powershell
docker compose start payment
docker compose logs -f payment
```

Ready deve cair até 0; os três pedidos devem concluir. Para demonstrar especificamente Ctrl+C conforme o roteiro da atividade, use os terminais Python descritos adiante: interrompa o terminal de payment, envie pedidos e execute-o novamente.

### 3. DLQ

No laboratório clique `Enviar pagamento recusado`. O worker publica `pagamento.recusado` e depois executa `basic_nack(requeue=False)` na mensagem original. No Management abra `norma.dlq`, use Get messages com requeue=true para não retirar a evidência, e exiba o corpo e o cabeçalho `x-death` (`reason: rejected`). Não confunda o evento de recusa com a mensagem original morta: são dois destinos diferentes.

### 4. Duas réplicas e rajada

```powershell
docker compose up -d --scale payment=2
docker compose logs -f payment
```

Confirme 2 consumers em `norma.payment`. No laboratório web clique `Disparar 10 pedidos`. Mostre os IDs e os nomes diferentes dos contêineres nos logs. Prefetch=1 permite no máximo uma mensagem não confirmada por consumidor. Não prometa uma divisão exatamente 5/5: o escalonamento depende do tempo de processamento.

### 5. Persistência ao reiniciar o broker

Pare payment, envie 2 pedidos, anote Ready, execute `docker compose restart rabbitmq`, espere o healthcheck ficar saudável e abra o painel novamente. Os pedidos devem continuar na fila. Inicie payment e mostre a conclusão. Nunca use `docker compose down -v` durante a demonstração: essa opção remove os volumes.

## Alternativa: broker em Docker e workers em terminais Python

Este modo facilita o Ctrl+C e a visualização de dois terminais independentes.

```powershell
docker compose stop api payment inventory notifications
docker compose up -d rabbitmq
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Abra terminais na raiz do projeto e execute um comando em cada:

```powershell
.venv/Scripts/python.exe -m api.app
.venv/Scripts/python.exe -m workers.worker payment payment-A
.venv/Scripts/python.exe -m workers.worker inventory inventory-A
.venv/Scripts/python.exe -m workers.worker notifications notifications-A
```

Para escala, abra outro terminal: `.venv/Scripts/python.exe -m workers.worker payment payment-B`.

Também é possível usar RabbitMQ nativo no Windows com Erlang compatível e o plugin rabbitmq_management. Configure o usuário/senha acima ou a variável `RABBITMQ_URL`. O código usa AMQP real em ambos os modos. O banco `data/norma.db` pertence à execução nativa; o Docker usa o volume `app_data`. Não compartilham automaticamente os mesmos pedidos.

## Confiabilidade e limites

- Exchanges/filas duráveis e mensagens delivery_mode=2.
- Publisher confirms + mandatory=True para detectar falha de publicação/roteamento.
- auto_ack=False; ACK somente após transação de negócio e publicação dos eventos resultantes.
- NACK sem requeue para erro de negócio/payload inválido; a DLQ não tem consumidor automático.
- Outbox no SQLite evita perder eventos entre gravação local e publicação. Na inicialização dos workers, eventos pendentes são reenviados; reenvios HTTP usam Idempotency-Key.
- Dedupe por `(service,event_id)` e reserva por pedido: reentregas não repetem a regra de negócio.
- Entrega pelo menos uma vez, não exatamente uma vez. Duplicações de transporte são possíveis.
- SQLite compartilhado é uma simplificação didática; as comunicações de negócio entre workers são por eventos. Produção deveria separar bancos, autenticar clientes e implementar políticas de retry/observabilidade.
- Fila clássica com DLX é adequada ao laboratório de um nó. Não garante tolerância à perda do disco nem dead-lettering sem perda em falhas simultâneas; considerar quorum queues em produção.
- A API responde 503 se o broker não confirmar a publicação; não apresenta sucesso fictício. O pedido permanece na outbox e pode ser retomado.

## Testes

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_rules.py -v
```

Teste integrado: mantenha apenas RabbitMQ ativo, sem outra API/worker local ou Docker, pois o script cria e encerra seus próprios processos:

```powershell
.venv/Scripts/python.exe tests/integration.py
```

O teste cria 16 pedidos distintos (normal, 3 de caos, 1 recusado, 10 de rajada e 1 de idempotência), registra JSON e logs em `evidencias/`. Ele não substitui a gravação dos cliques na aplicação web solicitada pelo professor.

## Entrega

Atividade: 28/11/2026. Enviar PDF técnico (máximo 6 páginas), MP4 de 10-15 minutos com fala de todos e ZIP completo. Preencher nomes dos integrantes antes de entregar. O vídeo deve mostrar a execução real; use o roteiro de gravação fornecido, sem narrar resultados esperados como se fossem medidos.

## Referências

- https://www.rabbitmq.com/docs/confirms
- https://www.rabbitmq.com/docs/dlx
- https://www.rabbitmq.com/docs/consumers
- https://docs.docker.com/desktop/setup/install/windows-install/
- Fotografias ilustrativas: Unsplash (arquivos locais no frontend). Fontes: Google Fonts (DM Sans e Manrope; fallback local sans-serif).
