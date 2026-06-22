#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "esp_event_base.h"
#include "esp_netif_types.h"
#include "esp_wifi.h"
#include "esp_system.h"
#include "esp_wifi_default.h"
#include "esp_wifi_types_generic.h"
#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_netif.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "mqtt_client.h"

#include "pb.h"
#include "pb_decode.h"
#include "pb_encode.h"
#include "sensors.pb.h"

#define ESP_WIFI_SSID      "Iphone de Juan pablo"
#define ESP_WIFI_PASS      "buenastardes"
#define BROKER_URI         "mqtt://192.168.0.10:1883"

#define MQTT_TOPIC_TEMP "iot/rpi4/temp"
#define MQTT_TOPIC_ACCEL "iot/rpi4/accel"

static const char *TAG = "ESP32_SUB";

// --- MANEJADOR DE EVENTOS WI-FI ---
static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGI(TAG, "Desconectado del AP Wi-Fi, reintentando...");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Conectado a la Raspberry! IP asignada: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}

// --- MANEJADOR DE EVENTOS MQTT ---
static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_mqtt_event_handle_t event = event_data;
    esp_mqtt_client_handle_t client = event->client;

    switch ((esp_mqtt_event_id_t)event_id) {
        case MQTT_EVENT_CONNECTED:
            ESP_LOGI(TAG, "Conectado al Broker MQTT en la Raspberry!");
            // Suscripción a los tópicos (Requisito 5.2)
            esp_mqtt_client_subscribe(client, "iot/rpi4/accel", 0);
            esp_mqtt_client_subscribe(client, "iot/rpi4/temp", 0);
            esp_mqtt_client_subscribe(client, "iot/status/rpi4", 0);
            break;
            
        case MQTT_EVENT_DATA:
            // event->topic y event->data NO son strings terminados en null ('\0')
            // Se debe usar su longitud (topic_len y data_len) para compararlos y leerlos.
            
            if (strncmp(event->topic, "iot/rpi4/accel", event->topic_len) == 0 ||
                strncmp(event->topic, "iot/rpi4/temp", event->topic_len) == 0) {
                
                // 1. Inicializar la estructura del mensaje vacía (Nanopb)
                iot_SensorEnvelope envelope = iot_SensorEnvelope_init_zero;
                
                // 2. Crear un stream de entrada desde los bytes recibidos de MQTT
                pb_istream_t stream = pb_istream_from_buffer((uint8_t*)event->data, event->data_len);
                
                // 3. Deserializar el payload
                if (pb_decode(&stream, iot_SensorEnvelope_fields, &envelope)) {
                    // Verificar qué tipo de mensaje venía dentro del 'oneof'
                    if (envelope.which_payload == iot_SensorEnvelope_accel_tag) {
                        ESP_LOGI(TAG, "[MQTT QoS %d] Acelerómetro - Origen: %s | TS: %lu | ax: %.2f | ay: %.2f | az: %.2f", 
                                 event->qos,
                                 envelope.source_id,
                                 (unsigned long)envelope.payload.accel.timestamp_ms,
                                 envelope.payload.accel.ax,
                                 envelope.payload.accel.ay,
                                 envelope.payload.accel.az);
                    } 
                    else if (envelope.which_payload == iot_SensorEnvelope_temp_tag) {
                        ESP_LOGI(TAG, "[MQTT QoS %d] Temperatura - Origen: %s | TS: %lu | Temp: %.2f °C", 
                                 event->qos,
                                 envelope.source_id,
                                 (unsigned long)envelope.payload.temp.timestamp_ms,
                                 envelope.payload.temp.temperature);
                    }
                } else {
                    ESP_LOGE(TAG, "Error decodificando Protobuf: %s", PB_GET_ERROR(&stream));
                }
            } 
            else if (strncmp(event->topic, "iot/status/rpi4", event->topic_len) == 0) {
                // El status es un JSON puro, lo imprimimos tal cual
                ESP_LOGI(TAG, "[Status Heartbeat] %.*s", event->data_len, event->data);
            }
            break;
            
        case MQTT_EVENT_DISCONNECTED:
            ESP_LOGI(TAG, "Desconectado del Broker MQTT");
            break;
            
        default:
            break;
    }
}

// --- FUNCIÓN PRINCIPAL ---
void app_main(void) {
    ESP_LOGI(TAG, "Iniciando Firmware del Suscriptor IoT...");

    // 1. Inicializar la memoria Flash NVS (requerida por el Wi-Fi)
    nvs_flash_init();

    // 2. Iniciar conexión Wi-Fi (como Station)
    esp_netif_init();

    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);

    esp_event_handler_instance_t wifi_any_evh;

    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &wifi_any_evh);

    esp_event_handler_instance_t got_ip_evh;
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &got_ip_evh);

    esp_wifi_set_mode(WIFI_MODE_STA);
    wifi_config_t wifi_config = {
        .sta = {
            .ssid = ESP_WIFI_SSID,
            .password = ESP_WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);

    esp_wifi_start();

    // 3. Dar tiempo a que obtenga IP del DHCP de la Raspberry
    vTaskDelay(pdMS_TO_TICKS(3000)); 

    // 4. Configurar y arrancar Cliente MQTT
    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = BROKER_URI,
    };
    esp_mqtt_client_handle_t client = esp_mqtt_client_init(&mqtt_cfg);
    esp_mqtt_client_register_event(client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_mqtt_client_start(client);
}
