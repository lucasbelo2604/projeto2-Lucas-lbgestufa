"""
CCM520 - Projeto 2: Estufa inteligente integrada ao FIWARE.
ESP32 / MicroPython / Wokwi / MQTT / IoT Agent JSON.

Pinagem desta montagem: DHT22=19, solo=32, LDR=33, rele=25, servo=18, LED alerta=23.
"""

import dht
import gc
import json
import network
import time
from machine import ADC, Pin, PWM
from umqtt.simple import MQTTClient


# ---------------------------------------------------------------------------
# 1. Configuracao
# ---------------------------------------------------------------------------
SSID = "Wokwi-GUEST"
SENHA = ""

BROKER = "broker.hivemq.com"
PORTA = 1883

API_KEY = "lbgestufa"
DEVICE_ID = "estufa2604"
CLIENT_ID = "esp32_" + API_KEY + "_" + DEVICE_ID

TOPICO_MEDIDAS = "/json/" + API_KEY + "/" + DEVICE_ID + "/attrs"
TOPICO_COMANDOS = "/" + API_KEY + "/" + DEVICE_ID + "/cmd"
TOPICO_RESULTADO = "/json/" + API_KEY + "/" + DEVICE_ID + "/cmdexe"

PIN_DHT = 19
PIN_SOLO = 32       # ADC1_CH4
PIN_LUZ = 33        # ADC1_CH5
PIN_RELE = 25
PIN_SERVO = 18
PIN_LED_SOLO_SECO = 23
LIMIAR_SOLO_SECO = 30

INTERVALO_MIN = 2000           # ms
INTERVALO_MAX = 10000          # ms
intervalo = 2000               # ms; comando setInterval altera este valor
envio_ativo = True             # comando setSending altera este estado

# Calibracao inicial para a simulacao (ADC de 12 bits: 0 a 4095).
# Em ambos os sensores, ADC menor corresponde a maior percentual.
# Faixas de demonstração verificadas no Wokwi; não são calibração de sensores físicos.
ADC_SECO_ESCURO = 4095
ADC_MOLHADO_CLARO = 0


# ---------------------------------------------------------------------------
# 2. Hardware
# ---------------------------------------------------------------------------
sensor_umidade_solo = ADC(Pin(PIN_SOLO))
sensor_umidade_solo.atten(ADC.ATTN_11DB)

sensor_luz = ADC(Pin(PIN_LUZ))
sensor_luz.atten(ADC.ATTN_11DB)

sensor_dht22 = dht.DHT22(Pin(PIN_DHT))

rele = Pin(PIN_RELE, Pin.OUT)
rele.value(0)

servomotor = PWM(Pin(PIN_SERVO), freq=50)
angulo_servo = 0
led_solo_seco = Pin(PIN_LED_SOLO_SECO, Pin.OUT)
led_solo_seco.value(0)


def mover_servo(angulo):
    """Aproximacao Wokwi: duty 26 (0 graus), 77 (90), 128 (180)."""
    global angulo_servo
    duty = int(26 + angulo * 102 / 180)
    servomotor.duty(duty)
    angulo_servo = angulo


mover_servo(0)


def porcentagem_adc_invertida(leitura):
    """0..4095 -> 100..0 por cento, com limitacao de faixa."""
    valor = 100 * (ADC_SECO_ESCURO - leitura) / (ADC_SECO_ESCURO - ADC_MOLHADO_CLARO)
    return round(max(0, min(100, valor)), 1)


def ler_sensores():
    """Le as quatro grandezas e devolve as chaves do provisionamento."""
    try:
        sensor_dht22.measure()
        temperatura = sensor_dht22.temperature()
        umidade_ar = sensor_dht22.humidity()
    except OSError as erro:
        print("Falha na leitura do DHT22:", erro)
        return None

    adc_solo = sensor_umidade_solo.read()
    adc_luz = sensor_luz.read()
    umidade_solo = porcentagem_adc_invertida(adc_solo)
    luminosidade = porcentagem_adc_invertida(adc_luz)

    return {
        "t": round(temperatura, 1),
        "rh": round(umidade_ar, 1),
        "sm": umidade_solo,
        "lx": luminosidade,
    }


# ---------------------------------------------------------------------------
# 3. Wi-Fi (mantido conforme o esqueleto)
# ---------------------------------------------------------------------------
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
if not wlan.isconnected():
    wlan.connect(SSID, SENHA)
    inicio = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), inicio) > 15000:
            raise RuntimeError("Wi-Fi nao conectou")
        time.sleep(0.5)
print("Wi-Fi ok. IP:", wlan.ifconfig()[0])


# ---------------------------------------------------------------------------
# 4. Medidas: ESP32 -> MQTT -> IoT Agent -> Orion
# ---------------------------------------------------------------------------
def publicar_medidas():
    dados = ler_sensores()
    if dados is None:
        return False

    led_solo_seco.value(1 if dados["sm"] < LIMIAR_SOLO_SECO else 0)
    dados["r"] = rele.value()       # relayState: 0 ou 1
    dados["wa"] = angulo_servo       # windowAngle: 0 a 180
    dados["si"] = intervalo // 1000  # samplingInterval: segundos

    payload = json.dumps(dados)
    cliente.publish(TOPICO_MEDIDAS.encode(), payload.encode())
    print("tempo ESP32:", time.ticks_ms(), "medidas ->", payload)
    return True


# ---------------------------------------------------------------------------
# 5. Comandos: Orion -> IoT Agent -> MQTT -> ESP32
# ---------------------------------------------------------------------------
def converter_inteiro(valor):
    """Aceita 1, 1.0 ou '1'; recusa fracionarios e tipos invalidos."""
    if isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
        inteiro = int(numero)
        if numero == inteiro:
            return inteiro
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def executar_comando(nome, valor):
    global intervalo, envio_ativo

    if nome not in ("setRelay", "setServo", "setInterval", "setSending"):
        return "ERRO: comando desconhecido"

    numero = converter_inteiro(valor)
    if numero is None:
        return "ERRO: valor invalido"

    if nome == "setRelay":
        if numero not in (0, 1):
            return "ERRO: setRelay aceita 0 ou 1"
        rele.value(numero)

    elif nome == "setServo":
        if not 0 <= numero <= 180:
            return "ERRO: setServo aceita 0 a 180"
        mover_servo(numero)

    elif nome == "setInterval":
        if not INTERVALO_MIN <= numero * 1000 <= INTERVALO_MAX:
            return "ERRO: setInterval aceita 2 a 10 segundos"
        intervalo = numero * 1000

    elif nome == "setSending":
        if numero not in (0, 1):
            return "ERRO: setSending aceita 0 ou 1"
        envio_ativo = (numero == 1)

    print("executado:", nome, numero)
    return "OK"


def ao_receber(topico, mensagem):
    global ultimo_envio
    print("comando <-", topico, mensagem)

    try:
        comandos = json.loads(mensagem.decode())
    except (ValueError, TypeError):
        print("Mensagem ignorada: JSON invalido")
        return

    if not isinstance(comandos, dict):
        print("Mensagem ignorada: esperava objeto JSON")
        return

    if not comandos:
        print("Mensagem ignorada: objeto JSON vazio")
        return

    respostas = {}
    for nome, valor in comandos.items():
        respostas[nome] = executar_comando(nome, valor)

    payload = json.dumps(respostas)
    cliente.publish(TOPICO_RESULTADO.encode(), payload.encode())
    print("resultado ->", payload)

    # Uma mudanca de atuador ou intervalo e refletida imediatamente no Orion.
    # Com setSending=0, somente as medidas param, nao os comandos.
    if envio_ativo and publicar_medidas():
        ultimo_envio = time.ticks_ms()




# ---------------------------------------------------------------------------
# 6. Broker MQTT e reconexao automatica
# ---------------------------------------------------------------------------
cliente = None

ultimo_envio = time.ticks_ms() - intervalo
ultima_limpeza = time.ticks_ms()
ultima_tentativa = time.ticks_add(time.ticks_ms(), -5000)

# ---------------------------------------------------------------------------
# 7. Laco principal
# ---------------------------------------------------------------------------
while True:
    agora = time.ticks_ms()

    if cliente is None:
        # Tenta reconectar a cada 5 segundos
        if time.ticks_diff(agora, ultima_tentativa) >= 5000:
            ultima_tentativa = agora

            if not wlan.isconnected():
                print("Wi-Fi desconectado. Tentando reconectar...")
                try:
                    wlan.connect(SSID, SENHA)
                except OSError as erro:
                    print("Falha Wi-Fi:", erro)

            else:
                try:
                    novo_cliente = MQTTClient(
                        CLIENT_ID.encode(),
                        BROKER,
                        port=PORTA,
                        keepalive=60
                    )

                    novo_cliente.set_callback(ao_receber)
                    novo_cliente.connect()
                    novo_cliente.subscribe(TOPICO_COMANDOS.encode())

                    cliente = novo_cliente

                    print("MQTT conectado:", BROKER)
                    print("Assinando:", TOPICO_COMANDOS)

                    # Publicar uma medida logo apos reconectar
                    ultimo_envio = time.ticks_ms() - intervalo

                except OSError as erro:
                    print("Falha na conexao MQTT:", erro)
                    cliente = None

    else:
        try:
            if not wlan.isconnected():
                raise OSError("Wi-Fi desconectado")

            # Verifica comandos sem bloquear
            cliente.check_msg()

            agora = time.ticks_ms()

            if envio_ativo and time.ticks_diff(
                agora, ultimo_envio
            ) >= intervalo:
                publicar_medidas()
                ultimo_envio = agora

        except OSError as erro:
            print("Conexao MQTT perdida:", erro)

            try:
                cliente.disconnect()
            except OSError:
                pass

            cliente = None

    # Limpeza periodica de memoria
    if time.ticks_diff(agora, ultima_limpeza) >= 15000:
        gc.collect()
        ultima_limpeza = agora

