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
#include "portmacro.h"
#include "sensors.pb.h"

#define ESP_WIFI_SSID      "tarea3"
#define ESP_WIFI_PASS      "password"
#define BROKER_URI         "mqtt://192.168.10.1:1883"

#define MQTT_TOPIC_TEMP "iot/rpi4/temp"
#define MQTT_TOPIC_ACCEL "iot/rpi4/accel"

static const char *TAG = "ESP32_SUB";

long long acc_msg = 0;
long long temp_msg = 0;
long long status_msg = 0;

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
void mqtt_event_handler(void* handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_mqtt_event_t *event = event_data;

    switch (event_id) {
        case MQTT_EVENT_CONNECTED:
            ESP_LOGI(TAG, "Conectado al Broker MQTT en la Raspberry!");
            // Suscripción a los tópicos (Requisito 5.2)
            esp_mqtt_client_subscribe(event->client, MQTT_TOPIC_ACCEL, 0);
            esp_mqtt_client_subscribe(event->client, MQTT_TOPIC_TEMP, 0);
            esp_mqtt_client_subscribe(event->client, "iot/status/rpi4", 1);
            break;
            
        case MQTT_EVENT_DATA:


            if (strncmp(event->topic, "iot/status/rpi4", event->topic_len) == 0) {
                status_msg++;
                printf("[STATUS] %.*s\n", event->data_len, event->data);
            }
            else {
                iot_SensorEnvelope envelope = iot_SensorEnvelope_init_zero;
                pb_istream_t stream = pb_istream_from_buffer ( (uint8_t*)event->data , event->data_len );

                if (!pb_decode(&stream, iot_SensorEnvelope_fields, &envelope)) {
                    ESP_LOGE(TAG, "DECODE FAILED: %s", PB_GET_ERROR(&stream));
                    return;
                }
                if (envelope.which_payload == iot_SensorEnvelope_accel_tag ) {
                    acc_msg++;
                    ESP_LOGI ( TAG , " Accel : ts = %.lu ax =%.2f ay =%.2f az =%.2f " ,
                    envelope.payload.accel.timestamp_ms,
                    envelope.payload.accel.ax ,
                    envelope.payload.accel.ay ,
                    envelope.payload.accel.az);
                    }
                if (envelope.which_payload == iot_SensorEnvelope_temp_tag) {
                    temp_msg++;
                    ESP_LOGI(TAG, "Temp: ts = %.lu temp = %.1f C", 

                        envelope.payload.temp.temperature);
                }
            }
            break;
            
        case MQTT_EVENT_DISCONNECTED:
            ESP_LOGI(TAG, "Desconectado del Broker MQTT");
            esp_mqtt_client_reconnect(event->client);
            break;
            
        default:
            break;
    }
}

void subscriber_task() {
    for(;;) {
        vTaskDelay(1 / portTICK_PERIOD_MS);
        printf("Mensajes en Aceleración: %.lld", acc_msg);
        printf("Mensajes en Temperatura: %.lld", temp_msg);
        printf("Mensajes en Status: %.lld", status_msg);

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

    xTaskCreate(subscriber_task, "subscriber_task", 4096, NULL, 5, NULL);
}
