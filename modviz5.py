import serial
import minimalmodbus
import time
import csv
from datetime import datetime
import threading
import collections # For deque (double-ended queue) for plotting buffer

# PyQtGraph imports
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, pyqtSlot
import pyqtgraph as pg

# --- Sensor configurations (unchanged) ---
SENSORS = [
    {
        'PORT': 'COM12',        # IMPORTANT: Change this to your serial port
        'BAUDRATE': 115200,     # IMPORTANT: Match your sensor's baud rate
        'BYTESIZE': 8,
        'PARITY': serial.PARITY_NONE, # IMPORTANT: Match parity (serial.PARITY_EVEN, serial.PARITY_ODD)
        'STOPBITS': 1,          # IMPORTANT: Match stop bits (1 or 2)
        'TIMEOUT': 0.03,        # Modbus response timeout in seconds
        'SLAVE_ADDRESS': 1,     # IMPORTANT: Match your sensor's Modbus address
        'REGISTER_ADDRESS': 512, # (40513 - 40001 = 512) - 0-indexed Modbus address
        'NUMBER_OF_REGISTERS': 3,# Number of consecutive registers to read
        'FUNCTION_CODE': 3,     # For "03holding" -> Read Holding Registers
        'REGISTER_INDEX_TO_LOG': 0, # Index of the register value to log from the read block (e.g., 0 for raw)
        'SCALE_FACTOR': 1.0,    # Example: if raw value is 100 and real value is 10.0, factor is 10.0
        'NAME': 'Sensor 1',     # Unique name for this sensor
        'UNIT': 'mm'        # Unit for CSV header
    },
    {
        'PORT': 'COM12',
        'BAUDRATE': 115200,
        'BYTESIZE': 8,
        'PARITY': serial.PARITY_NONE,
        'STOPBITS': 1,
        'TIMEOUT': 0.03,
        'SLAVE_ADDRESS': 2,     # Different slave address for the second sensor
        'REGISTER_ADDRESS': 0,
        'NUMBER_OF_REGISTERS': 2,
        'FUNCTION_CODE': 3,
        'REGISTER_INDEX_TO_LOG': 1, # Index for encoder value 'x'
        'SCALE_FACTOR': 1.0,
        'NAME': 'Sensor 2',
        'UNIT': 'mm',
        # --- Custom scaling function for Sensor 2 ---
        'scale_function': lambda x_val: ((x_val - 1000) * 100) / 4096
    }
]

# CSV file setup (changed to include start date and time)
start_time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
CSV_FILENAME = f'sensor_data_{start_time_str}.csv'
CSV_HEADER = ['Timestamp'] + [f"{sensor['NAME']} ({sensor['UNIT']})" for sensor in SENSORS]

# --- Helper functions (mostly unchanged) ---
def setup_minimalmodbus_instrument(sensor_config):
    """Sets up and returns a minimalmodbus instrument object."""
    instrument = minimalmodbus.Instrument(
        sensor_config['PORT'],
        sensor_config['SLAVE_ADDRESS']
    )
    instrument.serial.baudrate = sensor_config['BAUDRATE']
    instrument.serial.bytesize = sensor_config['BYTESIZE']
    instrument.serial.parity = sensor_config['PARITY']
    instrument.serial.stopbits = sensor_config['STOPBITS']
    instrument.serial.timeout = sensor_config['TIMEOUT']
    instrument.mode = minimalmodbus.MODE_RTU
    # instrument.debug = True
    return instrument

def read_sensor_data(instrument, sensor_config):
    """Reads data from a single sensor and applies scaling."""
    try:
        registers = instrument.read_registers(
            sensor_config['REGISTER_ADDRESS'],
            sensor_config['NUMBER_OF_REGISTERS'],
            sensor_config['FUNCTION_CODE']
        )
        # Note: Added check for 'REGISTER_INDEX_TO_TO_LOG' typo fix
        index_to_log = sensor_config.get('REGISTER_INDEX_TO_LOG', 0)
        raw_value = registers[index_to_log]

        if 'scale_function' in sensor_config:
            scaled_value = sensor_config['scale_function'](raw_value)
        else:
            scaled_value = raw_value * sensor_config['SCALE_FACTOR']

        return scaled_value

    except Exception as e:
        # print(f"Error reading {sensor_config['NAME']} (Slave Address: {sensor_config['SLAVE_ADDRESS']}): {e}")
        return None

def write_to_csv(data_rows, filename=CSV_FILENAME, header=CSV_HEADER):
    """Appends multiple rows of data to the CSV file, creating it if it doesn't exist."""
    if not data_rows:
        return

    file_exists = False
    try:
        with open(filename, 'r') as f:
            file_exists = True
    except FileNotFoundError:
        pass

    with open(filename, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(header)
        writer.writerows(data_rows)


# --- Sensor Reader Thread ---
class SensorReader(QThread):
    # Signal to emit when new data is available
    data_ready = pyqtSignal(list) # Emits a list of sensor values

    def __init__(self, sensors_config, csv_filename, csv_header, parent=None):
        super().__init__(parent)
        self.sensors_config = sensors_config
        self.csv_filename = csv_filename
        self.csv_header = csv_header
        self._running = True
        self.readings_buffer = []

        self.instruments = []
        # Desired frequencies
        self.sensor_read_frequency_hz = 30
        self.csv_write_frequency_s = 1.0
        self.target_loop_duration = 1.0 / self.sensor_read_frequency_hz

    def run(self):
        # Setup instruments (moved here as it runs in the thread's context)
        for sensor_config in self.sensors_config:
            try:
                instrument = setup_minimalmodbus_instrument(sensor_config)
                self.instruments.append({'instrument': instrument, 'config': sensor_config})
                print(f"Successfully configured {sensor_config['NAME']} on {sensor_config['PORT']}")
            except Exception as e:
                print(f"Failed to configure {sensor_config['NAME']}: {e}")

        if not self.instruments:
            print("No sensors successfully configured in thread. Exiting thread.")
            self._running = False # Stop the thread if no instruments are setup
            return

        print(f"Sensor reading thread started. Logging to {self.csv_filename}")

        start_time_csv_write = time.time()

        while self._running:
            timestamp_for_reading = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            loop_start_time = time.time()

            current_data_row_values = []
            for item in self.instruments:
                sensor_value = read_sensor_data(item['instrument'], item['config'])
                current_data_row_values.append(sensor_value)

            # Emit data for visualization
            self.data_ready.emit(current_data_row_values)

            # Combine timestamp and sensor values, then add to buffer for CSV
            self.readings_buffer.append([timestamp_for_reading] + current_data_row_values)

            # Check if it's time to write to CSV
            current_time_for_csv = time.time()
            if (current_time_for_csv - start_time_csv_write) >= self.csv_write_frequency_s:
                if self.readings_buffer:
                    write_to_csv(self.readings_buffer, self.csv_filename, self.csv_header)
                    print(f"Appended {len(self.readings_buffer)} readings to CSV.")
                    self.readings_buffer = []
                start_time_csv_write = current_time_for_csv

            # Control the sensor reading frequency
            loop_end_time = time.time()
            time_spent_in_loop = loop_end_time - loop_start_time
            sleep_duration = self.target_loop_duration - time_spent_in_loop

            if sleep_duration > 0:
                time.sleep(sleep_duration)
            # else:
            #     print(f"Warning (Sensor Thread): Loop took too long ({time_spent_in_loop:.4f}s), unable to maintain {self.sensor_read_frequency_hz}Hz.")

        # Cleanup when thread stops
        print("\nSensor reading thread stopping. Writing any remaining buffered data to CSV...")
        if self.readings_buffer:
            write_to_csv(self.readings_buffer, self.csv_filename, self.csv_header)
            print(f"Appended {len(self.readings_buffer)} remaining readings to CSV.")
        
        # Close serial ports
        for item in self.instruments:
            if item['instrument'].serial.is_open:
                item['instrument'].serial.close()
                print(f"Closed serial port for {item['config']['NAME']}")

    def stop(self):
        self._running = False
        self.wait() # Wait for the thread to finish its current loop


# --- Main Application Window for Visualization ---
class MainWindow(QMainWindow):
    def __init__(self, sensor_reader_thread, parent=None):
        super().__init__(parent)
        self.sensor_reader_thread = sensor_reader_thread
        self.setWindowTitle("Real-time Sensor Data")
        self.setGeometry(100, 100, 1000, 600) # x, y, width, height

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Configure PyQtGraph plot
        pg.setConfigOption('background', 'w') # White background
        pg.setConfigOption('foreground', 'k') # Black foreground (text, axes)

        self.plot_widgets = []
        self.plot_curves = []
        self.data_buffers = [] # For storing data for plotting

        # Initialize plots for each sensor
        for i, sensor_config in enumerate(SENSORS):
            plot_widget = pg.PlotWidget(title=f"{sensor_config['NAME']} Live Data")
            plot_widget.setLabel('left', sensor_config['NAME'], units=sensor_config['UNIT'])
            plot_widget.setLabel('bottom', "Time (s)")
            plot_widget.addLegend() # Add legend for multiple curves if needed
            
            # Use different colors for different sensors if plotting multiple on one graph
            # Or create separate plots as done here
            pen = pg.mkPen(color=pg.intColor(i, len(SENSORS)), width=2) # Automatic distinct colors
            curve = plot_widget.plot(name=sensor_config['NAME'], pen=pen)
            
            self.plot_widgets.append(plot_widget)
            self.plot_curves.append(curve)
            self.data_buffers.append(collections.deque(maxlen=200)) # Store last 200 points for rolling plot

            self.layout.addWidget(plot_widget)

        # Connect the signal from the sensor reader thread to a slot in MainWindow
        self.sensor_reader_thread.data_ready.connect(self.update_plot)

        # A timer to ensure the plot updates regularly even if the data stream is not perfectly smooth
        # Or if we want to batch plot updates (e.g., plot every 50ms even if data comes at 20ms)
        # For simplicity, we'll update directly when data_ready is emitted.
        # If you experience lag, you might buffer data here and update on a QTimer.

    @pyqtSlot(list) # Decorator to mark this as a slot for signal connection
    def update_plot(self, sensor_values):
        current_time_s = time.time() # Time for the x-axis of the plot

        # Update each sensor's plot
        for i, value in enumerate(sensor_values):
            if value is not None:
                # Store (time, value) pair. For time, use relative time from start or simply an index.
                # Using an index for now to keep it simple, or 'time.time()' directly
                self.data_buffers[i].append(value) # Just the value
            else:
                self.data_buffers[i].append(float('nan')) # Append NaN for missing data

            # Get the current data to plot. For time axis, we can use indices or actual timestamps.
            # Using simple index for X for now.
            x_data = list(range(len(self.data_buffers[i])))
            y_data = list(self.data_buffers[i])
            
            self.plot_curves[i].setData(x_data, y_data)
        
        # To make the X-axis represent actual time or a rolling window correctly,
        # you'll typically plot `elapsed_time` or an index from a fixed-size buffer.
        # For simplicity, the `maxlen` of the deque creates a rolling window.
        # If you need absolute timestamps on the X-axis, you'd store (timestamp, value) pairs
        # in the buffer and adjust setData accordingly. For now, it plots sequential points.

    def closeEvent(self, event):
        # Ensure the sensor reading thread stops gracefully when the GUI window is closed
        self.sensor_reader_thread.stop()
        super().closeEvent(event)


# --- Main execution ---
if __name__ == "__main__":
    app = QApplication([]) # Initialize the Qt Application

    # Create the sensor reader thread
    sensor_reader = SensorReader(SENSORS, CSV_FILENAME, CSV_HEADER)

    # Create the main window, passing the sensor reader thread to it
    main_window = MainWindow(sensor_reader)
    main_window.show()

    # Start the sensor reading thread
    sensor_reader.start()

    # Start the Qt event loop
    app.exec_()