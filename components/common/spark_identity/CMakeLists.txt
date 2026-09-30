idf_component_register(SRCS "spark_identity.c" "spark_relay.c" INCLUDE_DIRS "include" REQUIRES mbedtls efuse esp_hw_support json esp_http_client esp-tls)
