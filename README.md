# Projeto 2 — Estufa inteligente (FIWARE)

**Pasta do projeto:** `projeto2-Lucas-lbgestufa`  
**Grupo/API key:** `lbgestufa`  
**Device ID:** `estufa2604`  
**Entidade NGSI-v2:** `urn:ngsi-ld:Greenhouse:001` (`Greenhouse`)  
**FIWARE-Service / ServicePath:** `fei` / `/estufa`  
**Integrante:** Lucas Belo Gaspardo

**RA:** 22.224.007-9

Este README reúne a identificação, arquitetura, instruções de conexão, decisões e respostas R1–R8. O relatório técnico completo também está em `relatorio.pdf`.

## Objetivo e arquitetura

Integrar o firmware MicroPython da ESP32 com HiveMQ, uma ponte Mosquitto, FIWARE IoT Agent JSON e Orion; persistir notificações históricas pelo Cygnus em MySQL; e consultar o histórico no Grafana. Um consumidor HTTP recebe o alerta de umidade de solo abaixo de 30%.

```text
ESP32 / Wokwi ⇄ HiveMQ público ⇄ ponte Mosquitto local ⇄ IoT Agent JSON ⇄ Orion
                                                               ├─ Cygnus → MySQL → Grafana
                                                               └─ consumidor de alertas
```

A ponte recebe do broker público as medidas e respostas de comando do grupo e encaminha ao broker local; comandos publicados pelo IoT Agent local seguem no sentido inverso. O IoT Agent fica ligado apenas ao Mosquitto local. O Compose preserva os serviços do material de apoio e acrescenta o consumidor e o simulador de lâmpada de exemplo.

## Estrutura entregue

```text
projeto2-Lucas-lbgestufa/
├── README.md
├── firmware/
│   ├── main.py
│   └── diagram.json
├── plataforma/
│   ├── docker-compose.yml
│   ├── mosquitto/mosquitto.conf
│   ├── mysql/01-usuario-grafana.sql
│   └── servicos/
├── postman/Projeto 2.postman_collection.json
├── grafana/painel-estufa.json
└── relatorio.pdf
```

Os JSONs `postman/resultado-etapa*.json` são evidências das execuções concluídas. A coleção Postman foi personalizada a partir do material-base da aula para esta API key, dispositivo, entidade e modelo de dados. O projeto adaptado está em [Estufa Inteligente - Lucas - Projeto 2](https://wokwi.com/projects/480526241555040257); `firmware/main.py` e `firmware/diagram.json` reproduzem a simulação. O circuito foi reorganizado e ganhou um indicador local de solo seco. Como ponto de partida, foi usado o [projeto Wokwi compartilhado de Jonathan Campo](https://wokwi.com/projects/480422279547961345), com autorização de adaptação informada pelo responsável por esta entrega; a autoria original permanece registrada no diagrama e as alterações desta versão são descritas neste README.

## Hardware e firmware

| Componente | GPIO | Uso |
|---|---:|---|
| DHT22 | 19 | temperatura e umidade relativa |
| Potenciômetro (representa o sensor de solo no Wokwi) | 32 | ADC1_CH4, umidade do solo |
| LDR | 33 | ADC1_CH5, luminosidade |
| Relé | 25 | ligar/desligar |
| Servo da ventilação | 18 | posição de 0 a 180° |
| LED vermelho + resistor 220 Ω | 23 | alerta local quando solo < 30% |

O firmware entregue é a versão executada no projeto Wokwi vinculado acima. Ele usa `Wokwi-GUEST` sem senha e conecta a `broker.hivemq.com:1883`. Em uma placa física, altere `SSID` e `SENHA` para a rede local e copie `firmware/main.py` como `main.py`; não grave senha pessoal no repositório. `firmware/diagram.json` registra as peças e ligações da simulação Wokwi. A pinagem foi reorganizada para usar GPIO32/33 nos dois canais ADC1 e separar a leitura do sensor dos pinos de atuação. Um LED vermelho com resistor de 220 Ω acende localmente quando a umidade simulada do solo fica abaixo de 30%; ele não altera o modelo NGSI.

O firmware Wokwi usa faixa ADC provisória de 12 bits, mapeada para percentuais. Isso reproduz a direção observada no simulador; não representa calibração medida do sensor físico. Recalibre no circuito real antes de apresentar os percentuais como medição física. Não há senha Wi-Fi pessoal no pacote.

### Tópicos MQTT

| Função | Tópico |
|---|---|
| Medidas (ESP32 → plataforma) | `/json/lbgestufa/estufa2604/attrs` |
| Comandos (plataforma → ESP32) | `/lbgestufa/estufa2604/cmd` |
| Resultado dos comandos | `/json/lbgestufa/estufa2604/cmdexe` |

O broker HiveMQ usado no exercício é público e não autentica/autoriza os tópicos. A API key é um identificador do tópico do projeto, não deve ser tratada como segredo ou mecanismo de segurança.

## Como iniciar e conectar

Pré-requisitos: Windows com Docker Desktop iniciado em modo Linux/WSL2, conexão à internet para baixar imagens e uma ESP32 ou projeto Wokwi para testar o firmware.

1. Extraia o ZIP preservando a pasta `projeto2-Lucas-lbgestufa`.
2. Configure Wi-Fi e calibração em `firmware/main.py`. Para hardware real, confirme ligações e GPIOs na tabela acima.
3. No PowerShell, entre em `projeto2-Lucas-lbgestufa/plataforma` e execute:

   ```powershell
   docker compose pull
   docker compose up -d
   docker compose ps
   ```

   Espere os nove serviços do Compose ficarem `healthy`. Consulte os logs, se necessário, com `docker compose logs -f mosquitto` ou `docker compose logs -f iot-agent`.
4. Grave `firmware/main.py` na ESP32/Wokwi. A conexão MQTT usa HiveMQ público na porta TCP 1883. A ponte no Compose encaminha apenas a API key `lbgestufa` e este Device ID.
5. Importe `postman/Projeto 2.postman_collection.json` no Postman. A coleção contém hosts e variáveis do ambiente local, e os corpos necessários para o grupo, dispositivo, histórico e alerta já estão preenchidos. Rode a coleção inteira pelo Runner começando pela pasta `0 - Recomeçar do zero`, com a estufa ligada. A pasta 0 apaga provisionamento/subscrições existentes do serviço/caminho antes de recriá-los; não use `docker compose down -v` a menos que queira apagar também os volumes do banco, Orion e Grafana.
6. Abra Orion em `http://localhost:1026/version`, IoT Agent em `http://localhost:4041/iot/about`, consumidor em `http://localhost:3001/notificacoes`, e Grafana em `http://localhost:3000`.

A coleção usa o host local: Orion `1026`, IoT Agent de provisionamento `4041`, IoT Agent HTTP `7896`, Cygnus `5080` (gestão)/`5050` (notificações), Grafana `3000` e consumidor `3001`.

## Modelo de dados e comandos

| `object_id` no MQTT | Atributo NGSI | Tipo/unidade |
|---|---|---|
| `t` | `temperature` | Number, °C |
| `rh` | `relativeHumidity` | Number, % |
| `sm` | `soilMoisture` | Number, 0–100% após calibração |
| `lx` | `illuminance` | Number, 0–100% após calibração |
| `r` | `relayState` | Number, 0/1 |
| `wa` | `windowAngle` | Number, 0–180° |
| `si` | `samplingInterval` | Number, 2–10 s |

Atributos estáticos: `name` e `location`. Nesta entrega simulada, `location` usa `[0,0]` como valor de demonstração e não representa a localização real de uma estufa. Comandos aceitos: `setRelay` (0/1), `setServo` (0–180), `setInterval` (2–10 s) e `setSending` (0/1). O firmware responde `OK` ou `ERRO: motivo` no tópico `cmdexe`. `setSending=0` suspende as medidas periódicas, mas mantém a escuta de comandos ativa.

## Histórico, alerta e Grafana

A subscrição do Orion envia os sete atributos de medida em formato `normalized` para o Cygnus, que os grava como linhas na tabela `fei.estufa` do MySQL. O alerta usa a condição `soilMoisture<30` e encaminha `soilMoisture`, `relayState` e `TimeInstant` em `keyValues` ao consumidor, com `throttling` de 10 s.

Para configurar o Grafana em uma instalação nova: abra `http://localhost:3000` (credenciais iniciais do laboratório `admin` / `admin`, troque a senha no primeiro acesso); adicione uma fonte MySQL com endereço `mysql-db:3306`, banco `fei`, usuário de leitura `grafana`, senha de laboratório `grafana2026` e TLS desativado; use **Save & test**. Importe `grafana/painel-estufa.json`, selecione essa fonte na variável `DS_MYSQL` e salve como **Estufa inteligente**. O dashboard tem temperatura/umidade, solo, estado do relé e luminosidade. Ele só mostra histórico depois que houver medidas notificadas e persistidas.

## Decisões e respostas R1–R8

**R1 — Assinatura compartilhada e ponte.** Uma shared subscription distribui uma mensagem correspondente entre clientes do mesmo grupo. Os IoT Agents JSON do laboratório compartilham filtros/grupo `json`; conectá-los diretamente ao HiveMQ público pode fazer um agente de outra equipe consumir uma publicação. A ponte isola o IoT Agent no Mosquitto local e encaminha apenas tópicos do grupo. Medidas e `cmdexe` entram; `cmd` sai.

**R2 — API key exclusiva.** A chave compõe os tópicos e identifica o grupo. Se duas equipes reutilizarem chave e Device ID, publicarão/assinarão os mesmos tópicos, misturando medidas e comandos. Client IDs MQTT também precisam ser exclusivos, pois conexões concorrentes com o mesmo ID se substituem.

**R3 — Rejeitar dispositivos não provisionados.** Em broker público, qualquer cliente pode tentar publicar. Com autoprovisionamento, um tópico inventado com a chave do grupo poderia criar entidades inesperadas, contaminar histórico e gerar alertas. O grupo foi configurado com `autoprovision=false`.

**R4 — Caminho da medida até o Grafana.** ESP32 publica JSON em HiveMQ; a ponte traz a medida ao Mosquitto local; o IoT Agent converte `object_id` para atributos NGSI e atualiza o Orion; o Orion notifica Cygnus por HTTP; Cygnus persiste no MySQL; Grafana consulta MySQL e apresenta as séries.

**R5 — Caminho e status do comando.** Um PATCH NGSI-v2 no Orion inicia o comando. IoT Agent publica no tópico `cmd`, a ponte encaminha a HiveMQ e a ESP32 executa no GPIO. A resposta volta em `cmdexe` e atualiza o contexto. `PENDING` significa aguardando; `OK` significa que houve resposta do dispositivo, não que o valor foi necessariamente aceito. Consulte também o campo de informação do comando.

**R6 — Comandos com envio desativado.** `setSending=0` interrompe somente as publicações periódicas. A conexão e `check_msg` permanecem ativos para receber `setSending=1` e retomar o envio.

**R7 — Orion, MySQL e formatos.** Orion guarda o estado atual e comandos; MySQL preserva histórico. `normalized` contém estrutura e tipos para persistência no Cygnus; `keyValues` é adequado ao consumidor simples do alerta.

**R8 — Riscos no broker público.** Escuta indevida expõe condições da estufa; publicações falsas podem contaminar contexto ou acionar atuadores. Em uso real, prefira broker privado/gerenciado, autenticação, ACL por dispositivo/tópico, TLS e proteção também nas APIs FIWARE. O broker público deste exercício não fornece essas proteções.

## Verificação realizada e pendências reais

Na validação final, os nove serviços ficaram `healthy` e a configuração Compose passou na validação. Etapa 1 Postman: 6 requisições e 10 asserções sem falha. Etapa 2: 6 requisições e 31 asserções sem falha. Etapa 3, com o circuito revisado em execução no Wokwi: 16 requisições e 39 asserções sem falha, cobrindo medidas, quatro comandos e limites inválidos. Etapa 4: 13 requisições e 41 asserções sem falha, cobrindo subscrições, Cygnus, histórico MySQL, alerta, fonte de dados e painel Grafana. Os resultados ficam em `postman/resultado-etapa1.json`, `resultado-etapa2.json`, `resultado-etapa3.json` e `resultado-etapa4.json`.

A Etapa 3 foi executada somente no simulador Wokwi e validou o caminho para HiveMQ, ponte MQTT, IoT Agent e Orion, além dos quatro comandos e seus limites. O indicador local de solo seco também foi observado no simulador nos dois estados (solo seco e acima do limiar). Não houve teste em placa física. Para manter o escopo reproduzível no simulador, `location` e as faixas ADC têm valores de demonstração; eles não afirmam uma localização nem calibração de sensores físicos.

## Organização do projeto

O PDF `relatorio.pdf` contém a arquitetura, decisões, respostas R1–R8 e o registro de validações/pendências. Nesta pasta estão os arquivos executáveis e documentos finais, organizados conforme o modelo de entrega.



