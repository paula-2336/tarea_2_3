import sys
import os
import json
import csv
import time
import numpy as np
import paho.mqtt.client as mqtt
from PyQt6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

# Asegurar que se puedan importar los archivos generados de protobuf
sys.path.append(os.path.join(os.path.dirname(__file__), 'proto'))
try:
    from sensors_pb2 import SensorEnvelope
except ImportError:
    print("Error: No se encontró sensors_pb2.py. Recuerda compilar el archivo proto primero.")

# --- Hilo del Cliente MQTT (Suscriptor) ---
class MQTTWorker(QtCore.QThread):
    # Señales Qt para comunicar los hilos de manera segura (Requisito 6.1)
    accel_received = QtCore.pyqtSignal(dict)
    temp_received = QtCore.pyqtSignal(dict)
    status_received = QtCore.pyqtSignal(dict)

    def __init__(self, broker_ip, port=1883):
        super().__init__()
        self.broker_ip = broker_ip
        self.port = port
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Conectado al Broker MQTT en {self.broker_ip}")
            # Suscripción a los tópicos requeridos (Requisito 5.2)
            self.client.subscribe("iot/rpi4/accel", qos=0)
            self.client.subscribe("iot/rpi4/temp", qos=0)
            self.client.subscribe("iot/status/rpi4", qos=0)
        else:
            print(f"Error de conexión al broker MQTT. Código: {rc}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        qos = msg.qos
        payload = msg.payload

        try:
            if topic == "iot/status/rpi4":
                # Mensaje Heartbeat es el único en formato JSON (Requisito 4.3)
                data = json.loads(payload.decode('utf-8'))
                data['qos'] = qos
                self.status_received.emit(data)
            
            elif topic in ["iot/rpi4/accel", "iot/rpi4/temp"]:
                # Deserialización con Protocol Buffers usando SensorEnvelope (Requisito 3.1, 100)
                envelope = SensorEnvelope()
                envelope.ParseFromString(payload)
                source_id = envelope.source_id
                
                if envelope.HasField("accel") and topic == "iot/rpi4/accel":
                    accel_data = {
                        "topic": topic,
                        "qos": qos,
                        "source": source_id,
                        "timestamp_ms": envelope.accel.timestamp_ms,
                        "ax": envelope.accel.ax,
                        "ay": envelope.accel.ay,
                        "az": envelope.accel.az
                    }
                    self.accel_received.emit(accel_data)
                    
                elif envelope.HasField("temp") and topic == "iot/rpi4/temp":
                    temp_data = {
                        "topic": topic,
                        "qos": qos,
                        "source": source_id,
                        "timestamp_ms": envelope.temp.timestamp_ms,
                        "temperature": envelope.temp.temperature
                    }
                    self.temp_received.emit(temp_data)
        except Exception as e:
            print(f"Error procesando mensaje en tópico {topic}: {e}")

    def run(self):
        try:
            self.client.connect(self.broker_ip, self.port, 60)
            self.client.loop_forever()
        except Exception as e:
            print(f"Error en el bucle del cliente MQTT Worker: {e}")

# --- Ventana Principal de la Interfaz Gráfica ---
class IoTDashboard(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dashboard IoT de Configuración Dinámica - Tarea 2")
        self.resize(900, 650)
        
        # Archivo de configuración
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        # Estructuras de datos para gráficos y estadísticas
        self.accel_buffer = {"t": [], "ax": [], "ay": [], "az": []}
        self.temp_history = {"t": [], "val": []}
        
        # Datos para el Panel de Estado (Requisito 6.2.3)
        self.status_data = {
            "accel": {"qos": 0, "count": 0, "last_time": time.time()},
            "temp": {"qos": 0, "count": 0, "last_time": time.time()}
        }
        
        # Estado del Registro CSV (Requisito 6.3)
        self.is_logging = False
        self.csv_file = None
        self.csv_writer = None

        self.init_ui()
        self.load_network_and_start_mqtt()
        
        # Timer para actualizar el panel de estado cada 1 segundo
        self.status_timer = QtCore.QTimer()
        self.status_timer.timeout.connect(self.update_status_panel)
        self.status_timer.start(1000)

    def init_ui(self):
        # Widget Central y Layout principal
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # Barra Superior de Registro CSV Común
        csv_layout = QtWidgets.QHBoxLayout()
        self.btn_csv = QtWidgets.QPushButton("Iniciar Registro CSV")
        self.btn_csv.clicked.connect(self.toggle_csv_logging)
        self.lbl_csv_status = QtWidgets.QLabel("Registro: Inactivo")
        csv_layout.addWidget(self.btn_csv)
        csv_layout.addWidget(self.lbl_csv_status)
        csv_layout.addStretch()
        main_layout.addLayout(csv_layout)

        # QTabWidget para los 5 paneles requeridos (Requisito 6.2)
        self.tabs = QtWidgets.QTabWidget()
        main_layout.addWidget(self.tabs)

        # Creación de pestañas
        self.tab_accel = QtWidgets.QWidget()
        self.tab_temp = QtWidgets.QWidget()
        self.tab_status = QtWidgets.QWidget()
        self.tab_config = QtWidgets.QWidget()

        self.tabs.addTab(self.tab_accel, "Acelerómetro")
        self.tabs.addTab(self.tab_temp, "Temperatura")
        self.tabs.addTab(self.tab_status, "Estado Sistema")
        self.tabs.addTab(self.tab_config, "Configuración")

        self.setup_accel_tab()
        self.setup_temp_tab()
        self.setup_status_tab()
        self.setup_config_tab()

    # 1. PANEL ACELERÓMETRO (Requisito 6.2.1)
    def setup_accel_tab(self):
        layout = QtWidgets.QVBoxLayout(self.tab_accel)
        
        # Control de ventana deslizante
        win_layout = QtWidgets.QHBoxLayout()
        win_layout.addWidget(QtWidgets.QLabel("Ventana de visualización (s):"))
        self.spin_window = QtWidgets.QSpinBox()
        self.spin_window.setRange(2, 20)
        self.spin_window.setValue(5)
        win_layout.addWidget(self.spin_window)
        win_layout.addStretch()
        layout.addLayout(win_layout)

        # Gráfico pyqtgraph
        self.accel_plot = pg.PlotWidget(title="Datos del Acelerómetro Triaxial (50 Hz)")
        self.accel_plot.addLegend()
        self.accel_plot.showGrid(x=True, y=True)
        self.curve_x = self.accel_plot.plot(pen='r', name='Eje X')
        self.curve_y = self.accel_plot.plot(pen='g', name='Eje Y')
        self.curve_z = self.accel_plot.plot(pen='b', name='Eje Z')
        layout.addWidget(self.accel_plot)

        # Tabla de Indicadores Estadísticos de una ventana de 1000 muestras (~20s)
        self.table_stats = QtWidgets.QTableWidget(3, 3)
        self.table_stats.setHorizontalHeaderLabels(["RMS", "Peak Positivo", "Pico a Pico"])
        self.table_stats.setVerticalHeaderLabels(["Eje X", "Eje Y", "Eje Z"])
        self.table_stats.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_stats)

    # 2. PANEL TEMPERATURA (Requisito 6.2.2)
    def setup_temp_tab(self):
        layout = QtWidgets.QVBoxLayout(self.tab_temp)
        
        # Indicador numérico gigante
        self.lbl_temp_val = QtWidgets.QLabel("Último Valor: -- °C")
        self.lbl_temp_val.setFont(QtGui.QFont("Arial", 18, QtGui.QFont.Weight.Bold))
        self.lbl_temp_val.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_temp_val)

        # Gráfico histórico (Últimos 30 valores)
        self.temp_plot = pg.PlotWidget(title="Histórico de Temperatura (Últimos 30 valores)")
        self.temp_plot.showGrid(x=True, y=True)
        self.curve_temp = self.temp_plot.plot(pen=pg.mkPen('orange', width=2), symbol='o', symbolSize=6)
        layout.addWidget(self.temp_plot)

    # 3. PANEL ESTADO (Requisito 6.2.3)
    def setup_status_tab(self):
        layout = QtWidgets.QVBoxLayout(self.tab_status)
        self.table_status = QtWidgets.QTableWidget(2, 4)
        self.table_status.setHorizontalHeaderLabels(["Tópico", "QoS Activo", "Último mensaje (s atrás)", "Mensajes recibidos"])
        self.table_status.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        
        # Inicializar filas estáticas
        self.table_status.setItem(0, 0, QtWidgets.QTableWidgetItem("iot/rpi4/accel"))
        self.table_status.setItem(1, 0, QtWidgets.QTableWidgetItem("iot/rpi4/temp"))
        layout.addWidget(self.table_status)

    # 4. PANEL CONFIGURACIÓN (Requisito 2.2 y 6.2.4)
    def setup_config_tab(self):
        layout = QtWidgets.QVBoxLayout(self.tab_config)
        form_layout = QtWidgets.QFormLayout()

        # Controles Acelerómetro
        self.chk_accel = QtWidgets.QCheckBox("Habilitar")
        self.cmb_accel_qos = QtWidgets.QComboBox()
        self.cmb_accel_qos.addItems(["0", "1", "2"])
        form_layout.addRow(QtWidgets.QLabel("<b>Sensor Acelerómetro (50 Hz):</b>"))
        form_layout.addRow("Estado:", self.chk_accel)
        form_layout.addRow("Nivel de QoS:", self.cmb_accel_qos)

        # Línea divisoria espacial
        form_layout.addRow(QtWidgets.QLabel("<hr>"))

        # Controles Temperatura
        self.chk_temp = QtWidgets.QCheckBox("Habilitar")
        self.cmb_temp_qos = QtWidgets.QComboBox()
        self.cmb_temp_qos.addItems(["0", "1", "2"])
        form_layout.addRow(QtWidgets.QLabel("<b>Sensor Temperatura (1/15 Hz):</b>"))
        form_layout.addRow("Estado:", self.chk_temp)
        form_layout.addRow("Nivel de QoS:", self.cmb_temp_qos)

        layout.addLayout(form_layout)
        layout.addSpacerItem(QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Expanding))

        # Botones Aplicar y Recargar (Requisito 2.2.2 y 2.2.3)
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_reload = QtWidgets.QPushButton("Recargar")
        self.btn_reload.clicked.connect(self.reload_config_from_json)
        self.btn_apply = QtWidgets.QPushButton("Aplicar")
        self.btn_apply.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
        self.btn_apply.clicked.connect(self.apply_config_to_json)
        
        btn_layout.addWidget(self.btn_reload)
        btn_layout.addWidget(self.btn_apply)
        layout.addLayout(btn_layout)
        
        # Carga inicial de datos al abrir el software
        self.reload_config_from_json()

    # --- Lógica de Negocio y Callbacks Qt ---

    def load_network_and_start_mqtt(self):
        # Leer el JSON para saber a qué broker IP conectarse
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            broker_uri = config.get("mqtt_broker_uri", "mqtt://192.168.10.1:1883")
            # Extraer IP de la URI limpia (ej: mqtt://192.168.10.1:1883 -> 192.168.10.1)
            ip = broker_uri.split("//")[1].split(":")[0]
            
            # Lanzar el hilo del trabajador MQTT (Requisito 6.1)
            self.worker = MQTTWorker(ip)
            self.worker.accel_received.connect(self.handle_accel_data)
            self.worker.temp_received.connect(self.handle_temp_data)
            self.worker.status_received.connect(self.handle_status_data)
            self.worker.start()
        except Exception as e:
            print(f"Error cargando broker de red desde config.json: {e}")

    @QtCore.pyqtSlot(dict)
    def handle_accel_data(self, data):
        # Actualización de contadores del panel de estado
        self.status_data["accel"]["count"] += 1
        self.status_data["accel"]["qos"] = data["qos"]
        self.status_data["accel"]["last_time"] = time.time()

        # Guardar en estructura de datos para gráficos
        t_now = time.time()
        self.accel_buffer["t"].append(t_now)
        self.accel_buffer["ax"].append(data["ax"])
        self.accel_buffer["ay"].append(data["ay"])
        self.accel_buffer["az"].append(data["az"])

        # Limitar tamaño de la ventana de procesamiento local a las últimas 1000 muestras (Requisito 6.2.1)
        if len(self.accel_buffer["t"]) > 1000:
            for key in self.accel_buffer:
                self.accel_buffer[key].pop(0)

        # Actualizar gráfico según ventana deslizante (en segundos)
        win_size = self.spin_window.value()
        if self.accel_buffer["t"]:
            min_t = t_now - win_size
            # Encontrar índices dentro del rango de tiempo solicitado
            indices = [i for i, t in enumerate(self.accel_buffer["t"]) if t >= min_t]
            if indices:
                start_idx = indices[0]
                t_plot = np.array(self.accel_buffer["t"][start_idx:]) - self.accel_buffer["t"][0]
                self.curve_x.setData(t_plot, self.accel_buffer["ax"][start_idx:])
                self.curve_y.setData(t_plot, self.accel_buffer["ay"][start_idx:])
                self.curve_z.setData(t_plot, self.accel_buffer["az"][start_idx:])

        # Calcular Estadísticas sobre la ventana completa de 1000 muestras (Requisito 6.2.1)
        for i, axis in enumerate(["ax", "ay", "az"]):
            axis_data = np.array(self.accel_buffer[axis])
            if len(axis_data) > 0:
                rms = np.sqrt(np.mean(axis_data**2))
                peak_pos = np.max(axis_data)
                p2p = np.max(axis_data) - np.min(axis_data)
                
                self.table_stats.setItem(i, 0, QtWidgets.QTableWidgetItem(f"{rms:.3f}"))
                self.table_stats.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{peak_pos:.3f}"))
                self.table_stats.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{p2p:.3f}"))

        # Registro en CSV si está activo (Requisito 6.3)
        if self.is_logging and self.csv_writer:
            self.csv_writer.writerow([data["timestamp_ms"], data["source"], data["topic"], data["qos"], data["ax"], data["ay"], data["az"], ""])

    @QtCore.pyqtSlot(dict)
    def handle_temp_data(self, data):
        # Actualización de contadores del panel de estado
        self.status_data["temp"]["count"] += 1
        self.status_data["temp"]["qos"] = data["qos"]
        self.status_data["temp"]["last_time"] = time.time()

        # Indicador Numérico con Timestamp (Requisito 6.2.2)
        readable_ts = time.strftime('%H:%M:%S', time.localtime())
        self.lbl_temp_val.setText(f"Último Valor: {data['temperature']:.1f} °C  (Recibido: {readable_ts})")

        # Gráfico histórico de los últimos 30 valores
        self.temp_history["t"].append(time.time())
        self.temp_history["val"].append(data["temperature"])
        if len(self.temp_history["t"]) > 30:
            self.temp_history["t"].pop(0)
            self.temp_history["val"].pop(0)

        t_plot = np.array(self.temp_history["t"]) - (self.temp_history["t"][0] if self.temp_history["t"] else 0)
        self.curve_temp.setData(t_plot, self.temp_history["val"])

        # Registro en CSV si está activo (Requisito 6.3)
        if self.is_logging and self.csv_writer:
            self.csv_writer.writerow([data["timestamp_ms"], data["source"], data["topic"], data["qos"], "", "", "", data["temperature"]])

    @QtCore.pyqtSlot(dict)
    def handle_status_data(self, data):
        # Callback opcional si se quiere visualizar el Heartbeat JSON en consola
        pass

    # Actualizar Panel de Estado cada segundo (Requisito 6.2.3)
    def update_status_panel(self):
        now = time.time()
        for row, sensor in enumerate(["accel", "temp"]):
            s_info = self.status_data[sensor]
            sec_ago = int(now - s_info["last_time"]) if s_info["count"] > 0 else "--"
            
            self.table_status.setItem(row, 1, QtWidgets.QTableWidgetItem(str(s_info["qos"])))
            self.table_status.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{sec_ago} s atrás" if sec_ago != "--" else "--"))
            self.table_status.setItem(row, 3, QtWidgets.QTableWidgetItem(str(s_info["count"])))

    # --- Acciones de Botones de Configuración ---

    def reload_config_from_json(self):
        # Botón Recargar (Requisito 2.2.3)
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            sensors = config.get("sensors", {})
            
            # Cargar Acelerómetro
            accel = sensors.get("accel", {"enabled": True, "qos": 0})
            self.chk_accel.setChecked(accel.get("enabled", True))
            self.cmb_accel_qos.setCurrentText(str(accel.get("qos", 0)))
            
            # Cargar Temperatura
            temp = sensors.get("temp", {"enabled": True, "qos": 1})
            self.chk_temp.setChecked(temp.get("enabled", True))
            self.cmb_temp_qos.setCurrentText(str(temp.get("qos", 1)))
            
            QtWidgets.QMessageBox.information(self, "Recarga Exitosa", "Configuración recargada desde config.json.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo leer config.json: {e}")

    def apply_config_to_json(self):
        # Botón Aplicar (Requisito 2.2.2)
        if not os.path.exists(self.config_path):
            QtWidgets.QMessageBox.critical(self, "Error", "No se encuentra el archivo config.json base.")
            return
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            # Modificar diccionario en caliente
            config["sensors"]["accel"]["enabled"] = self.chk_accel.isChecked()
            config["sensors"]["accel"]["qos"] = int(self.cmb_accel_qos.currentText())
            
            config["sensors"]["temp"]["enabled"] = self.chk_temp.isChecked()
            config["sensors"]["temp"]["qos"] = int(self.cmb_temp_qos.currentText())
            
            # Guardar/Sobrescribir el archivo JSON (Requisito 2.2.2a)
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
                
            QtWidgets.QMessageBox.information(self, "Cambios Aplicados", "Configuración guardada. El publicador se adaptará automáticamente.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo escribir en config.json: {e}")

    # --- Control Guardado CSV ---
    def toggle_csv_logging(self):
        # Guardado de datos Dinámico (Requisito 6.3)
        if not self.is_logging:
            # Iniciar Registro
            filename = "iot_log_tarea2.csv"
            try:
                # Si el archivo no existe, crearlo con cabeceras requeridas
                file_exists = os.path.exists(filename)
                self.csv_file = open(filename, mode='a', newline='', encoding='utf-8')
                self.csv_writer = csv.writer(self.csv_file)
                
                if not file_exists:
                    # Columnas exactas del Requisito 6.3
                    self.csv_writer.writerow(["timestamp_ms", "source", "topic", "qos", "ax", "ay", "az", "temperature"])
                
                self.is_logging = True
                self.btn_csv.setText("Detener Registro CSV")
                self.btn_csv.setStyleSheet("background-color: #D32F2F; color: white;")
                self.lbl_csv_status.setText(f"Registrando en: {filename}")
            except Exception as e:
                print(f"Error abriendo archivo CSV: {e}")
        else:
            # Detener Registro
            self.is_logging = False
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
            self.btn_csv.setText("Iniciar Registro CSV")
            self.btn_csv.setStyleSheet("")
            self.lbl_csv_status.setText("Registro: Inactivo")

    def closeEvent(self, event):
        # Asegurar cerrar descriptores de archivos al cerrar ventana
        if self.csv_file:
            self.csv_file.close()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    dashboard = IoTDashboard()
    dashboard.show()
    sys.exit(app.exec())
