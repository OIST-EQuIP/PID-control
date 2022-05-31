#from curses import KEY_PPAGE
import sys
from PyQt5 import QtWidgets as qtw
from PyQt5 import QtCore as qtc
from PyQt5 import QtGui as qtg
from PyQt5 import uic
import pyqtgraph as pg
import numpy as np
from random import randint

import threading
from threading import Thread

import datetime as dt
import time
from time import perf_counter
import nidaqmx

from TLPM import TLPM
from ctypes import cdll,c_long, c_ulong, c_uint32,byref,create_string_buffer,c_bool,c_char_p,c_int,c_int16,c_double, sizeof, c_voidp

from simple_pid import PID

#Ui_Power_control, baseClass = uic.loadUiType('CO2_power_qt.ui')

class MainWindow(qtw.QWidget):

    def __init__(self, sampleinterval=0.1, timewindow=10., *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Connect to power meter
        resourceName = create_string_buffer(1024)
        self.tlPM = TLPM()
        deviceCount = c_uint32()
        self.tlPM.findRsrc(byref(deviceCount))
        self.tlPM.getRsrcName(c_int(0), resourceName)
        print(c_char_p(resourceName.raw).value)
        self.tlPM.open(resourceName, c_bool(True), c_bool(True))
        
        # Connect to DAQ board
        self.task = nidaqmx.Task()
        self.task.ao_channels.add_ao_voltage_chan("Dev1/ao1",'mychannel',0,1)
        self.task.start()
        print("--NI DAQ connected--")
        
        # Setup GUI
        self.close_button = qtw.QPushButton('close_button')
        self.close_button.clicked.connect(self.close_gui)

        self.checkBox = qtw.QCheckBox("PID", self)
        self.font = qtg.QFont()
        self.font.setPointSize(10)
        self.font.setBold(True)
        self.checkBox.setFont(self.font)
        self.checkBox.setObjectName("checkBox")
        self.checkBox.setChecked(False)
        self.checkBox.toggle()
        self.checkBox.stateChanged.connect(self.PID_run)

        self.p_doubleSpinBox = qtw.QDoubleSpinBox()
        self.p_doubleSpinBox.setMaximum(20.0)
        self.p_doubleSpinBox.setSingleStep(0.1)
        self.p_doubleSpinBox.setProperty("value", 2.0)
        self.p_doubleSpinBox.setObjectName("p_doubleSpinBox")
        self.i_doubleSpinBox = qtw.QDoubleSpinBox()
        self.i_doubleSpinBox.setMaximum(10.0)
        self.i_doubleSpinBox.setSingleStep(0.1)
        self.i_doubleSpinBox.setObjectName("i_doubleSpinBox")
        self.d_doubleSpinBox = qtw.QDoubleSpinBox()
        self.d_doubleSpinBox.setMaximum(10.0)
        self.d_doubleSpinBox.setSingleStep(0.1)
        self.d_doubleSpinBox.setObjectName("d_doubleSpinBox")
        self.sp_doubleSpinBox = qtw.QDoubleSpinBox()
        self.sp_doubleSpinBox.setMaximum(0.8)
        self.sp_doubleSpinBox.setSingleStep(0.05)
        self.sp_doubleSpinBox.setProperty("value", 0.2)
        self.sp_doubleSpinBox.setObjectName("sp_doubleSpinBox")
        setpoint = self.sp_doubleSpinBox.value()
        self.sp_doubleSpinBox.valueChanged.connect(self.write_power)
        self.label_4 = qtw.QLabel("Set Point")
        self.label_4.setFont(self.font)
        self.label = qtw.QLabel("P")
        self.label.setFont(self.font)
        self.label_2 = qtw.QLabel("I")
        self.label_2.setFont(self.font)
        self.label_3 = qtw.QLabel("D")
        self.label_3.setFont(self.font)
        self.pid = PID(self.p_doubleSpinBox.value(), self.i_doubleSpinBox.value(), self.d_doubleSpinBox.value(), setpoint)

        self.graphwidget = pg.PlotWidget()
        self.graphwidget.setBackground('w')
        styles = {'color':'r', 'font-size':'20px'}
        self.graphwidget.setLabel('left', 'Power (mW)', **styles)
        self.graphwidget.setLabel('bottom', '', **styles)
        self.x = list(np.zeros(100))
        self.y = list(np.zeros(100))
        pen = pg.mkPen(color=(0, 0, 255), width = 2)
        self.data_line = self.graphwidget.plot(self.x, self.y, pen=pen)  

        layout = qtw.QHBoxLayout()
        layout.addWidget(self.graphwidget)
        controls_layout = qtw.QVBoxLayout()
        sp_layout = qtw.QVBoxLayout()
        sp_layout.addWidget(self.label_4)
        sp_layout.addWidget(self.sp_doubleSpinBox)
        p_layout= qtw.QHBoxLayout()
        p_layout.addWidget(self.label)
        p_layout.addWidget(self.p_doubleSpinBox)
        i_layout= qtw.QHBoxLayout()
        i_layout.addWidget(self.label_2)
        i_layout.addWidget(self.i_doubleSpinBox)
        d_layout= qtw.QHBoxLayout()
        d_layout.addWidget(self.label_3)
        d_layout.addWidget(self.d_doubleSpinBox)
        PID_layout = qtw.QVBoxLayout()
        PID_layout.addLayout(p_layout)
        PID_layout.addLayout(i_layout)
        PID_layout.addLayout(d_layout)
        controls_layout.addWidget(self.close_button)
        controls_layout.addLayout(sp_layout)
        controls_layout.addWidget(self.checkBox)
        controls_layout.addLayout(PID_layout)
        layout.addLayout(controls_layout)
        self.setLayout(layout)
                
        self.show() 

         # QTimer
        self._bufsize = int(timewindow/sampleinterval)
        self._interval = int(sampleinterval*1000)
        self.timer = qtc.QTimer()
        self.timer.timeout.connect(self.update_plot_data)
        self.timer.start(self._interval)

    def PID_run(self, state):
        if self.checkBox.isChecked() == True:
            while self.checkBox.isChecked() == True:
                v = self.readTLPM()
                # Compute new output from the PID according to the systems current value
                control = self.pid(v)
                # Feed the PID output to the system and get its current value
                print(control)
                #self.write_power(control) 
        else:
            print('normal')
        # while self.checkBox.isChecked() == True:
        #     print("PID")
        #     v = self.readTLPM()
        #     # Compute new output from the PID according to the systems current value
        #     control = self.pid(v)
        #     # Feed the PID output to the system and get its current value
        #     print(control)
        #     #self.write_power(control) 
    
    def write_power(self, pow_in):
        v_output = 2.27*pow_in
        self.task.write(v_output)

    def _clamp(value, limits):
        lower, upper = limits
        if value is None:
            return None
        elif (upper is not None) and (value > upper):
            return upper
        elif (lower is not None) and (value < lower):
            return lower
        return value

    def readTLPM(self):
        #Read Value from DAQ device
        power_c =  c_double()
        self.tlPM.measPower(byref(power_c))
        Power = power_c.value
        return (float(Power))

    def update_plot_data(self):
        up_pow = self.readTLPM()
        self.x = self.x[1:]  # Remove the first y element.
        self.x.append(self.x[-1] + 1)  # Add a new value 1 higher than the last.
        self.y = self.y[1:]  # Remove the first
        self.y.append(self.readTLPM())  # Add a new random value.

        self.data_line.setData(self.x, self.y)  # Update the data.      
    
    def close_gui(self):
        self.tlPM.close()
        self.task.stop() # Terminate DAQ Device
        self.task.close()
        sys.exit(app.exec_())

if __name__ == '__main__':
    app = qtw.QApplication(sys.argv)
    w = MainWindow()
    sys.exit(app.exec_())