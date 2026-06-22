file(GLOB_RECURSE nanopb_runtime "nanopb/*.c")

idf_component_register(
    SRCS "main.c" 
         "proto/sensors.pb.c"
         "${nanopb_runtime}"
    INCLUDE_DIRS "." 
                 "proto"
                 "nanopb"
    PRIV_REQUIRES nvs_flash esp_wifi esp_event esp_netif mqtt
)
