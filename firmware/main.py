"""Firmware da estufa para ESP32 / Wokwi usando MicroPython e IoT Agent JSON."""

import dht
import gc
import json
import network
import time
from machine import ADC, Pin, PWM, idle
from umqtt.simple import MQTTClient

# ---------------------------------------------------------------------------
# Configuração. No Wokwi, use SSID="Wokwi-GUEST" e SENHA="".
# Nunca grave a senha real do Wi-Fi no repositório.
# ---------------------------------------------------------------------------
SSID = "nome_da_rede"
SENHA = "senha_da_rede"
BROKER = "broker.hivemq.com"
PORTA = 1883
API_KEY = "lbgestufa"
DEVICE_ID = "estufa2604"
CLIENT_ID = "esp32_" + API_KEY + "_" + DEVICE_ID

TOPICO_MEDIDAS = "/json/{}/{}/attrs".format(API_KEY, DEVICE_ID)
TOPICO_COMANDOS = "/{}/{}/cmd".format(API_KEY, DEVICE_ID)
TOPICO_RESULTADO = "/json/{}/{}/cmdexe".format(API_KEY, DEVICE_ID)

# Chaves abaixo devem coincidir com os object_id no provisionamento Postman.
ID_TEMPERATURA = "t"
ID_UMIDADE_AR = "rh"
ID_UMIDADE_SOLO = "sm"
ID_LUMINOSIDADE = "lx"
ID_RELE = "r"
ID_ANGULO = "wa"
ID_INTERVALO = "si"

INTERVALO_MIN = 2000
INTERVALO_MAX = 10000
intervalo = 3000
envio_ativo = True

# Calibração inicial de referência para ADC de 12 bits (0..4095).
# Substitua pelos valores medidos no sensor de vocês antes de usar os % como
# calibração real. Os sentidos podem variar conforme sensor/divisor de tensão.
SOLO_RAW_SECO = 4095
SOLO_RAW_MOLHADO = 0
LUZ_RAW_ESCURO = 0
LUZ_RAW_CLARO = 4095
ADC_MAX = 4095

# Hardware do Projeto 1: manter pinos e circuito.
sensor_umidade_solo = ADC(Pin(34))
sensor_umidade_solo.atten(ADC.ATTN_11DB)
sensor_luz = ADC(Pin(35))
sensor_luz.atten(ADC.ATTN_11DB)
sensor_dht22 = dht.DHT22(Pin(4))
rele = Pin(26, Pin.OUT)
rele.value(0)
servomotor = PWM(Pin(27), freq=50)
angulo_servo = 0


def mover_servo(angulo):
    """Aplique o ângulo validado ao servo, usando a conversão do esqueleto."""
    global angulo_servo
    angulo_servo = angulo
    servomotor.duty(int(40 + angulo / 180 * 75))


def mapear_percentual(raw, raw_zero, raw_cem):
    """Converte a leitura ADC para 0..100 respeitando os pontos de calibração."""
    if raw_zero == raw_cem:
        raise ValueError("pontos ADC de calibração precisam ser diferentes")
    valor = (raw - raw_zero) * 100.0 / (raw_cem - raw_zero)
    return round(min(100.0, max(0.0, valor)), 1)


def ler_sensores():
    """Retorna quatro valores numéricos; falha do DHT descarta só este ciclo."""
    try:
        sensor_dht22.measure()
        temperatura = round(sensor_dht22.temperature(), 1)
        umidade_ar = round(sensor_dht22.humidity(), 1)
        raw_solo = sensor_umidade_solo.read()
        raw_luz = sensor_luz.read()
        umidade_solo = mapear_percentual(raw_solo, SOLO_RAW_SECO, SOLO_RAW_MOLHADO)
        luminosidade = mapear_percentual(raw_luz, LUZ_RAW_ESCURO, LUZ_RAW_CLARO)
        return {
            "temperature": temperatura,
            "relativeHumidity": umidade_ar,
            "soilMoisture": umidade_solo,
            "illuminance": luminosidade,
        }
    except OSError as erro:
        print("leitura descartada; erro de sensor:", erro)
        return None
    except ValueError as erro:
        print("leitura descartada; calibração inválida:", erro)
        return None


# Wi-Fi. Em Wokwi: Wokwi-GUEST sem senha.
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
if not wlan.isconnected():
    wlan.connect(SSID, SENHA)
    inicio_wifi = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), inicio_wifi) > 15000:
            raise RuntimeError("Wi-Fi nao conectou")
        time.sleep(0.5)  # somente na conexão inicial, fora do laço principal
print("Wi-Fi ok. IP:", wlan.ifconfig()[0])


cliente = MQTTClient(CLIENT_ID, BROKER, port=PORTA, keepalive=60)
conectado = False
proxima_tentativa = time.ticks_ms()
ultimo_envio = time.ticks_add(time.ticks_ms(), -intervalo)
ultima_coleta_gc = time.ticks_ms()


def publicar_medidas():
    medidas = ler_sensores()
    if medidas is None:
        return False
    payload = {
        ID_TEMPERATURA: medidas["temperature"],
        ID_UMIDADE_AR: medidas["relativeHumidity"],
        ID_UMIDADE_SOLO: medidas["soilMoisture"],
        ID_LUMINOSIDADE: medidas["illuminance"],
        ID_RELE: rele.value(),
        ID_ANGULO: angulo_servo,
        ID_INTERVALO: intervalo // 1000,
    }
    cliente.publish(TOPICO_MEDIDAS, json.dumps(payload))
    print("medidas ->", TOPICO_MEDIDAS, payload)
    return True


def valor_inteiro(valor):
    """Aceita inteiro ou texto inteiro; rejeita bools, frações e valores nulos."""
    if isinstance(valor, bool) or valor is None:
        raise ValueError("valor deve ser inteiro")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        if valor != int(valor):
            raise ValueError("valor deve ser inteiro")
        return int(valor)
    if isinstance(valor, str):
        return int(valor.strip())
    raise ValueError("valor deve ser inteiro")


def executar_comando(nome, valor):
    global intervalo, envio_ativo
    try:
        numero = valor_inteiro(valor)
    except (TypeError, ValueError):
        return "ERRO: valor deve ser inteiro"

    if nome == "setRelay":
        if numero not in (0, 1):
            return "ERRO: setRelay aceita somente 0 ou 1"
        rele.value(numero)
        return "OK"
    if nome == "setServo":
        if numero < 0 or numero > 180:
            return "ERRO: setServo aceita valores de 0 a 180"
        mover_servo(numero)
        return "OK"
    if nome == "setInterval":
        if numero < 2 or numero > 10:
            return "ERRO: setInterval aceita valores de 2 a 10 segundos"
        intervalo = numero * 1000
        return "OK"
    if nome == "setSending":
        if numero not in (0, 1):
            return "ERRO: setSending aceita somente 0 ou 1"
        envio_ativo = (numero == 1)
        return "OK"
    return "ERRO: comando desconhecido"


def ao_receber(topico, mensagem):
    """Processa JSON de comandos e responde com a mesma chave de cada comando."""
    global conectado
    print("comando <-", topico, mensagem)
    try:
        comandos = json.loads(mensagem)
    except (ValueError, TypeError) as erro:
        print("JSON inválido ignorado:", erro)
        return
    if not isinstance(comandos, dict) or not comandos:
        print("comando inválido ignorado: esperado objeto JSON")
        return
    respostas = {}
    for nome, valor in comandos.items():
        respostas[nome] = executar_comando(nome, valor)
    try:
        cliente.publish(TOPICO_RESULTADO, json.dumps(respostas))
        print("resposta ->", TOPICO_RESULTADO, respostas)
        # setSending=0 desliga medidas; setSending=1 publica o estado logo após.
        if envio_ativo:
            publicar_medidas()
    except OSError as erro:
        print("falha ao responder comando:", erro)
        conectado = False


def conectar_mqtt():
    global conectado
    cliente.set_callback(ao_receber)
    cliente.connect()
    cliente.subscribe(TOPICO_COMANDOS)
    conectado = True
    print("MQTT conectado:", BROKER, "client_id:", CLIENT_ID)
    print("assinando:", TOPICO_COMANDOS)


# Laço principal cooperativo: check_msg não espera por mensagens; sem sleep/wait.
while True:
    agora = time.ticks_ms()

    if not conectado and time.ticks_diff(agora, proxima_tentativa) >= 0:
        try:
            conectar_mqtt()
        except OSError as erro:
            conectado = False
            print("MQTT indisponível; nova tentativa em 5 s:", erro)
            proxima_tentativa = time.ticks_add(agora, 5000)

    if conectado:
        try:
            cliente.check_msg()
        except OSError as erro:
            conectado = False
            proxima_tentativa = time.ticks_add(time.ticks_ms(), 5000)
            print("MQTT desconectado; reconectando:", erro)

    agora = time.ticks_ms()
    if conectado and envio_ativo and time.ticks_diff(agora, ultimo_envio) >= intervalo:
        try:
            publicar_medidas()
            ultimo_envio = agora
        except OSError as erro:
            conectado = False
            proxima_tentativa = time.ticks_add(agora, 5000)
            print("falha ao publicar medidas:", erro)

    if time.ticks_diff(agora, ultima_coleta_gc) >= 10000:
        gc.collect()
        ultima_coleta_gc = agora
    idle()