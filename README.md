# tarea_2_3

Version: nanopb-0.4.8


Comandos:

protoc --python_out=raspberry proto/sensors.proto

protoc -opacket.sensors.pb proto/sensors.proto

nanopb_generator packet.sensors.pb
