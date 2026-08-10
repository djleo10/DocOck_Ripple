"""
This is a GUI that uses PyQt6 (version 6.3.0).

It allows the user to send a TTL pulse of a user-defined width to any of the digital outputs (SMAs or parallel port).

Created on Thu May  5 14:56:04 2022

@author: kyleloizos
"""

import sys
import xipppy as xp
from time import sleep
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QCheckBox,
    QLineEdit,
    QLabel,
    QFormLayout,
    QVBoxLayout,
    QHBoxLayout
)


class MyApp(QWidget):
    """
    This class sets up a GUI to send a TTL pulse of a user-defined width to any of the digital outputs.
    """

    def __init__(self):
        """
        Initializes the MyApp class, including setting up the UI and initializing parameters.
        """
        super().__init__()
        self.connected = False
        self.init_ui()

    def init_ui(self):
        """
        Initializes the user interface of the application.
        """
        # Set window properties
        self.setWindowTitle('Digital Output')
        self.resize(300, 250)

        # Create top level layout
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Define button to connect/disconnect from processor
        self.connect_button = QPushButton("Connect to processor")
        self.connect_button.clicked.connect(self.connect_to_processor)

        # Define error label if xipppy can't connect to processor
        self.connect_error = self.create_connection_error_label()

        # Define form for setting pulse width
        pulsewidth_layout = QFormLayout()
        self.pulsewidth_text = QLineEdit("0.001")
        pulsewidth_layout.addRow("TTL width (s):", self.pulsewidth_text)

        # Define group of checkboxes for choosing digital output(s)
        digouts_layout = self.create_digital_output_checkboxes()

        # Define checkbox to enable parallel port input & text entry form
        parallel_layout = QHBoxLayout()
        self.parallel_enable = QCheckBox("Parallel port")
        parallel_layout.addWidget(self.parallel_enable)
        parallel_layout.addLayout(self.define_hex_text_entry())

        # Define button to send TTL
        self.send_ttl_button = QPushButton("Send TTL")
        self.send_ttl_button.clicked.connect(self.send_ttl)
        self.send_ttl_button.setEnabled(False)

        # Assemble window
        layout.addStretch()
        layout.addWidget(self.connect_button)
        layout.addWidget(self.connect_error)
        layout.addLayout(pulsewidth_layout)
        layout.addLayout(digouts_layout)
        layout.addLayout(parallel_layout)
        layout.addWidget(self.send_ttl_button)
        layout.addStretch()

    def create_connection_error_label(self):
        """
        Creates and styles the connection error label.
        """
        label = QLabel("Connection failed. Check power and connection.\n")
        label.setStyleSheet("color: red")
        label.setHidden(True)
        return label

    def create_digital_output_checkboxes(self):
        """
        Creates checkboxes for selecting digital outputs.
        """
        digouts_layout = QVBoxLayout()
        self.digouts = [QCheckBox(f"SMA {i + 1}") for i in range(4)]
        for checkbox in self.digouts:
            digouts_layout.addWidget(checkbox)
        return digouts_layout

    def define_hex_text_entry(self):
        """
        Creates a form layout for hex text entry related to parallel port output.
        """
        parallel_form = QFormLayout()
        self.parallel_text = QLineEdit("CAFE")
        validator = QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,4}"))
        self.parallel_text.setValidator(validator)
        parallel_form.addRow(self.parallel_text)

        self.parallel_text.setEnabled(False)
        self.parallel_enable.toggled.connect(self.parallel_checked)

        return parallel_form

    def parallel_checked(self):
        """
        Enables or disables the parallel port text entry based on the checkbox state.
        """
        self.parallel_text.setEnabled(self.parallel_enable.isChecked())

    def connect_to_processor(self):
        """
        Connects or disconnects from the processor.
        """
        self.connect_error.setHidden(True)
        xp._close()
        sleep(0.001)

        if not self.connected:
            self.try_connect()

        else:
            self.disconnect()

        sleep(0.001)

    def try_connect(self):
        """
        Attempts to connect to the processor using UDP, then TCP if UDP fails.
        """
        try:
            xp._open()
            self.on_connect_success("UDP")
        except:
            try:
                xp._open(use_tcp=True)
                self.on_connect_success("TCP")
            except:
                self.on_connect_failure()

    def on_connect_success(self, connection_type):
        """
        Handles actions to be performed upon a successful connection.
        """
        self.connected = True
        print(f"Connected over {connection_type}")
        self.send_ttl_button.setEnabled(True)
        self.connect_button.setText("Disconnect")

    def on_connect_failure(self):
        """
        Handles actions to be performed upon a failed connection.
        """
        self.connected = False
        self.connect_error.setHidden(False)
        print("Failed to connect to processor.")

    def disconnect(self):
        """
        Disconnects from the processor.
        """
        print("Closed connection")
        xp._close()
        self.send_ttl_button.setEnabled(False)
        self.connect_button.setText("Connect to processor")
        self.connected = False

    def send_ttl(self):
        """
        Sends a TTL pulse based on the user-defined settings.
        """
        out_channels, out_output, out_output2 = [], [], []

        if self.parallel_enable.isChecked():
            out_channels.append("4")
            out_output.append(str(int(self.parallel_text.text(), 16)))
            out_output2.append("0")

        for index, checkbox in enumerate(self.digouts):
            if checkbox.isChecked():
                out_channels.append(str(index))
                out_output.append("1")
                out_output2.append("0")

        digout_cmd1 = f"xp.digout([{','.join(out_channels)}], [{','.join(out_output)}])"
        digout_cmd2 = f"xp.digout([{','.join(out_channels)}], [{','.join(out_output2)}])"

        exec(digout_cmd1)
        sleep(float(self.pulsewidth_text.text()))
        exec(digout_cmd2)


if __name__ == "__main__":
    xp._close()
    app = QApplication([])

    window = MyApp()
    window.show()

    sys.exit(app.exec())