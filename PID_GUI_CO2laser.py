import sys
from PyQt5 import QtWidgets as qtw
from PyQt5 import QtCore as qtc
#from PyQt5 import QtGui as qtg
from PyQt5 import uic
from PyQt5.QtWidgets import QFileDialog
#from qtc import QThread

import pyqtgraph as pg
#from pyqtgraph import PlotWidget
import numpy as np
#from random import randint
import threading

from time import perf_counter
import nidaqmx
from TLPM import TLPM
from ctypes import cdll, c_uint32,byref,create_string_buffer,c_bool,c_char_p,c_int,c_double, sizeof, c_voidp

Ui_Power_control, baseClass = uic.loadUiType('mainwindow.ui')

class MainWindow(baseClass):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.ui = Ui_Power_control()
        self.ui.setupUi(self)
        self.show()
        
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
        self.settings = qtc.QSettings('Qt_apps','PID_App')
        #print(self.settings.fileName())

        self.ui.int_SpinBox.setProperty("value", self.settings.value('int'))
        self.ui.win_SpinBox.setProperty("value", self.settings.value('win'))
        self.interval = self.ui.int_SpinBox.value()
        self.win = self.ui.win_SpinBox.value()
        self.ui.int_SpinBox.valueChanged.connect(self.start_plot_timer)
        self.ui.inf_checkBox.stateChanged.connect(self.start_plot_timer)
        self.ui.start_button.clicked.connect(self.start_plot_timer)
        self.ui.stop_button.clicked.connect(self.stop_timer)
        self.ui.save_button.clicked.connect(self.save_data)
        self.ui.load_button.clicked.connect(self.load_data)
        self.ui.close_button.clicked.connect(self.close_gui)

        #self.ui.PID_checkBox.stateChanged.connect(self.PID_mode)
        self.ui.p_doubleSpinBox.setProperty("value", self.settings.value('p'))
        self.ui.i_doubleSpinBox.setProperty("value", self.settings.value('i'))
        self.ui.d_doubleSpinBox.setProperty("value", self.settings.value('d'))        
        self.ui.dt_SpinBox.setProperty("value", self.settings.value('dt'))
        self.dt = self.ui.dt_SpinBox.value()
        self.setpoint = self.ui.sp_doubleSpinBox.value()
        self.ui.sp_doubleSpinBox.valueChanged.connect(self.write_power)
        #self.ui.dt_SpinBox.valueChanged.connect(self.start_PID_timer)
        self.ui.graphwidget.setBackground('w')
        styles = {'color':'r', 'font-size':'20px'}
        self.ui.graphwidget.setLabel('left', 'Power (mW)', **styles)
        self.ui.graphwidget.setLabel('bottom', '', **styles)
        self.buff_pow = 0
        self.x = list(np.zeros(self.win))
        self.y = list(np.zeros(self.win))
        self.y_v = list(np.zeros(self.win))
        pen = pg.mkPen(color=(0, 0, 255), width = 2)
        #pen_v = pg.mkPen(color=(0, 255, 0), width = 2)
        self.data_line = self.ui.graphwidget.plot(self.x, self.y, pen=pen)
        #self.data_line_v = self.ui.graphwidget.plot(self.x, self.y_v, pen=pen_v)
        self.ui.graphwidget.setMouseEnabled(x=True, y=False)
        self.ui.graphwidget.setAutoVisible(x=None, y=True)
        self.show()

        self._bufsize = int(self.win)
        self.timer = qtc.QTimer()
        self.timer.timeout.connect(self.read_pow)
        self.timer.start(self.dt)

        self.time_0 = perf_counter()
        
        self.Calib = 2.27
        self.clock = np.zeros(2)
        self.counter = np.zeros(2)
        self.Error = np.zeros(2)
        self.Int = np.zeros(2)
    
    def read_pow(self):
        pow = self.readTLPM()
        self.clock[1] = perf_counter()
        time_int = self.clock[1]-self.clock[0]
        self.counter[1] = self.counter[0]+time_int
        time = self.counter[1]
        self.buff_pow = [time,pow]
        if self.ui.PID_checkBox.isChecked() == True:
            p_out, self.ERR, self.PID = self.PID_run(time_int, pow)
            self.write_power(p_out)
        self.clock[0] = self.clock[1]
        self.counter[0] = self.counter[1]

    def start_plot_timer(self):
        self.int = self.ui.int_SpinBox.value()
        self._bufsize = int(self.win)
        self.timer2 = qtc.QTimer()
        self.timer2.timeout.connect(self.plot_mode)
        self.timer2.start(self.int)

    def stop_timer(self):
        if self.timer.isActive() == True:
            self.timer.stop()
        if self.timer2.isActive() == True:
            self.timer2.stop()

    def plot_mode(self):
        [time,pow] = self.buff_pow
        if self.ui.PIDout_checkBox.isChecked() == True:
            self.update_plot_data(time, pow, self.PID)
        else:
            self.update_plot_data(time, pow, 0)
            
    def write_power(self, pow_in):
        v_output = 2.27*pow_in
        self.task.write(v_output)

    def PID_run(self, d_t, pow_in):
        #Measure time since last PID calculation
        #self.clock[1] = perf_counter()
        #d_t = self.clock[1]-self.clock[0]
        setpoint = self.ui.sp_doubleSpinBox.value()
        KP = self.ui.p_doubleSpinBox.value()
        KI = self.ui.i_doubleSpinBox.value()
        KD = self.ui.d_doubleSpinBox.value()
        # Compute new output from the PID according to the systems current value, create outputs
        self.Error[1] = float(setpoint - pow_in) #error entering the PID controller
        self.Der = (self.Error[1] - self.Error[0])/d_t #derivative of the error
        self.Int[1] = self.Int[0]+(self.Error[1] + self.Error[0])*d_t/2 #integration of the total error
        correction = KP*self.Error[1] + KI*self.Int[1]+ KD*self.Der #the three PID terms
        # Feed the PID output to the system and get its current value
        new_power = correction + pow_in
        p_out = self._clamp(new_power, (0, 1/self.Calib))
        # Pass new values for next reading
        #self.clock[0] = self.clock[1]
        self.Error[0] = self.Error[1]
        self.Int[0] = self.Int[1]
        return p_out, self.Error[1], correction, 

    def _clamp(self, value, limits):
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

    def update_plot_data(self, time, pow_in, error):
        self.win = self.ui.win_SpinBox.value()
        diff = self.win-len(self.x)
        if self.ui.inf_checkBox.isChecked() == True:
            self.x.append(time)  # Add a new value 1 higher than the last.
            self.y.append(pow_in)  # Add a new power value.
        else:
            if diff == 0:
                self.x = self.x[1:]  # Remove the first y element.
                self.x.append(time)  # Add a new value 1 higher than the last.
                self.y = self.y[1:]  # Remove the first
                self.y.append(pow_in)  # Add a new power value.
            elif diff > 0:
                #self.x = self.x[1:]  # Remove the first y element.
                self.x.append(time)  # Add a new value 1 higher than the last.
                #self.y = self.y[1:]  # Remove the first
                self.y.append(pow_in)  # Add a new power value.
            elif diff < 0:
                self.x = self.x[2:]  # Remove the first y element.
                self.x.append(time)  # Add a new value 1 higher than the last.
                self.y = self.y[2:]  # Remove the first
                self.y.append(pow_in)  # Add a new power value.
        self.data_line.setData(self.x, self.y)  # Update the data. 
    
    def save_data(self):
        option=QFileDialog.Options()
        option|=QFileDialog.DontUseNativeDialog
        filename, _ =QFileDialog.getSaveFileName(self,"Save File Window Title","PowerLog.txt","All Files (*)",options=option)
        file = open(filename,'w')
        #file.write(np.array2string(np.column_stack([self.x,self.y])))
        np.savetxt(file,np.column_stack([self.x,self.y]))
        file.close()

    def load_data(self):
        option=QFileDialog.Options()
        option|=QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getOpenFileName(self,"Load File Window Title","","Text Files (*.txt)",options=option)
        #file = open(filename,'r')
        #print(file.read())
        #file.close()
        array = np.loadtxt(filename,dtype=float)
        self.x=array[:,0]
        self.y=array[:,1]
        self.data_line.setData(self.x, self.y)  # Update the data.

    def close_gui(self):
        self.settings.setValue('p',self.ui.p_doubleSpinBox.value())
        self.settings.setValue('i',self.ui.i_doubleSpinBox.value())
        self.settings.setValue('d',self.ui.d_doubleSpinBox.value())
        self.settings.setValue('dt',self.ui.dt_SpinBox.value())
        self.settings.setValue('int',self.ui.int_SpinBox.value())
        self.settings.setValue('win',self.ui.win_SpinBox.value())
        self.tlPM.close()
        self.task.stop() # Terminate DAQ Device
        self.task.close()
        #self.timer1.stop()
        #☺self.timer2.stop()
        sys.exit(app.exec_())

if __name__ == '__main__':
    app = qtw.QApplication(sys.argv)
    w = MainWindow()
    sys.exit(app.exec_())