import sys
import os
import json
import time
import math
import random
import asyncio
import paho.mqtt.client as mqtt

# Asegurar que se puedan importar los archivos generados de protobuf
sys.path.append(os.path.join(os.path.dirname(__file__), 'proto'))
try:
    from sensors_pb2 import SensorEnvelope
except ImportError:
    print("Error crítico: No se encontró sensors_pb2.py.")
    sys.exit(1)

# Variables globales para configuración dinámica
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
current_config = {}

async def update_config_loop():
    """Lee el archivo config.json cada 1 segundo para actualizar la configuración en caliente (Requisito 2.2)."""
    global current_config
    while True:
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r') as f:
                    current_config = json.load(f)
        except Exception as e:
            print(f"Error leyendo config: {e}")
        await asyncio.sleep(1)

async def accel_publisher(client):
    """Simula y publica datos del acelerómetro a 50 Hz (cada 0.02 segundos)."""
    global current_config
    t0 = time.time()
    
    while True:
        # Extraer configuración en tiempo real
        sensors_cfg = current_config.get("sensors", {})
        accel_cfg = sensors_cfg.get("accel", {"enabled": True, "qos": 0})
        
        if accel_cfg.get("enabled", True):
            t = time.time() - t0
            
            # Generación de datos simulados (Requisito: modelo matemático)
            ax = 2.0 * math.sin(2 * math.pi * 1.5 * t) + random.uniform(-0.1, 0.1)
            ay = 2.0 * math.cos(2 * math.pi * 1.5 * t) + random.uniform(-0.1, 0.1)
            az = 9.81 + random.uniform(-0.2, 0.2)
            
            # Empaquetado con Protobuf
            envelope = SensorEnvelope()
            envelope.source_id = "rpi4"
            envelope.accel.timestamp_ms = int(time.time() * 1000)
            envelope.accel.ax = ax
            envelope.accel.ay = ay
            envelope.accel.az = az
            
            payload = envelope.SerializeToString()
            qos = accel_cfg.get("qos", 0)
            
            # Publicación MQTT
            client.publish("iot/rpi4/accel", payload, qos=qos)
            
        # Esperar 0.02s para cumplir los 50 Hz
        await asyncio.sleep(0.02)

async def temp_publisher(client):
    """Simula y publica datos de temperatura a 1/15 Hz (cada 15 segundos)."""
    global current_config
    t0 = time.time()
    
    while True:
        sensors_cfg = current_config.get("sensors", {})
        temp_cfg = sensors_cfg.get("temp", {"enabled": True, "qos": 1})
        
        if temp_cfg.get("enabled", True):
            t = time.time() - t0
            
            # Generación de datos simulados (Fluctuación térmica lenta)
            temperature = 22.5 + 5.0 * math.sin(2 * math.pi * 0.001 * t) + random.uniform(-0.5, 0.5)
            
            # Empaquetado con Protobuf
            envelope = SensorEnvelope()
            envelope.source_id = "rpi4"
            envelope.temp.timestamp_ms = int(time.time() * 1000)
            envelope.temp.temperature = temperature
            
            payload = envelope.SerializeToString()
            qos = temp_cfg.get("qos", 1)
            
            # Publicación MQTT
            client.publish("iot/rpi4/temp", payload, qos=qos)
            print(f"Temperatura publicada: {temperature:.2f} °C (QoS: {qos})")
            
        # Esperar 15s para cumplir el 1/15 Hz
        await asyncio.sleep(15.0)

async def status_publisher(client):
    """Publica un mensaje de Heartbeat en JSON para indicar que el publicador está vivo."""
    while True:
        status_data = {
            "status": "online",
            "uptime_s": int(time.time()),
            "active_sensors": []
        }
        
        sensors_cfg = current_config.get("sensors", {})
        if sensors_cfg.get("accel", {}).get("enabled", True):
            status_data["active_sensors"].append("accel")
        if sensors_cfg.get("temp", {}).get("enabled", True):
            status_data["active_sensors"].append("temp")
            
        payload = json.dumps(status_data)
        client.publish("iot/status/rpi4", payload, qos=0)
        
        # Latido cada 5 segundos
        await asyncio.sleep(5)

async def main():
    # 1. Cargar configuración inicial para obtener la IP del Broker
    global current_config
    try:
        with open(CONFIG_PATH, 'r') as f:
            current_config = json.load(f)
    except FileNotFoundError:
        print("Advertencia: No se encontró config.json, usando valores por defecto.")
        current_config = {"mqtt_broker_uri": "mqtt://127.0.0.1:1883"}

    # Extraer IP de la URI
    broker_uri = current_config.get("mqtt_broker_uri", "mqtt://127.0.0.1:1883")
    broker_ip = broker_uri.split("//")[1].split(":")[0]

    # 2. Configurar cliente MQTT
    client = mqtt.Client(client_id="rpi4_simulated_publisher")
    
    try:
        print(f"Conectando al Broker MQTT en {broker_ip}...")
        client.connect(broker_ip, 1883, 60)
        client.loop_start()  # Iniciar hilo en background de paho-mqtt
        print("Conectado exitosamente.")
    except Exception as e:
        print(f"Error al conectar con el broker MQTT: {e}")
        sys.exit(1)

    # 3. Lanzar todas las corutinas en paralelo
    print("Iniciando publicación de datos simulados...")
    await asyncio.gather(
        update_config_loop(),
        accel_publisher(client),
        temp_publisher(client),
        status_publisher(client)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nPublicador detenido por el usuario.")
