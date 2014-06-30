# skeleton for the FPGA device with multiple pseudoclocks each connected to a single output

from labscript_devices import labscript_device  #, BLACS_tab, BLACS_worker, runviewer_parser

from labscript import PseudoclockDevice, Pseudoclock, ClockLine, IntermediateDevice,\
    AnalogOut, DigitalOut, LabscriptError
    
import numpy as np

# Example
#
# import __init__ # only have to do this because we're inside the labscript directory
# from labscript import *
# from labscript_devices.FPGADevice import FPGADevice
#
# FPGADevice(name='fpga', n_outputs=2)
# AnalogOut('analog0', fpga.outputs[0], 'ao0')
# DigitalOut('digi0', fpga.outputs[1], 'digi1')
#
# start()
# analog0.ramp(0, duration=3, initial=0, final=1, samplerate=1e4)
# stop(1)


@labscript_device
class FPGADevice(PseudoclockDevice):
    """ device with n indiviually pseudoclocked outputs. """

    clock_limit = 1e6  # true value??
    clock_resolution = 1e-9  # true value??

    description = "FPGA-Device"
    allowed_children = [Pseudoclock]

    def __init__(self, name, n_outputs, usb_port, trigger_device=None, trigger_connection=None):
        PseudoclockDevice.__init__(self, name, trigger_device, trigger_connection)

        self.BLACS_connection = usb_port

        self.pseudoclocks = []
        self.clocklines = []
        self.output_devices = []
        # Create the internal pseudoclocks and clocklines, and the outputs
        for n in range(n_outputs):
            pc = Pseudoclock("fpga_pseudoclock{}".format(n), self, "clock_{}".format(n))
            self.pseudoclocks.append(pc)

            # Create the internal direct output clock_line
            cl = ClockLine("fpga_output{}_clock_line".format(n), pc, "fpga_internal{}".format(n))
            self.clocklines.append(cl)

            # Create the internal intermediate device (outputs) connected to the above clock line
            self.output_devices.append(OutputIntermediateDevice("fpga_output_device{}".format(n), cl))

    @property
    def outputs(self):
        """ Return list of connected Outputs. 
            An Output is None if the OutputDevice is not connected to an Output. """
        return self.output_devices
        #return [device.output for device in self.output_devices]

    def generate_code(self, hdf5_file):
        PseudoclockDevice.generate_code(self, hdf5_file)

        # group in which to save instructions for this device
        device_group = hdf5_file.create_group("/devices/{}".format(self.name))

        # reduce instructions?
        for i, pseudoclock in enumerate(self.pseudoclocks):
            # process the clock
            clock = np.zeros(len(pseudoclock.clock), dtype=[('period', int), ('reps', int)])

            for j, tick in enumerate(pseudoclock.clock):
                period = int(round(tick['step'] / self.clock_resolution))
                clock[j]['period'] = period
                clock[j]['reps'] = tick['reps']

            device_group.create_dataset("clocks/{}".format(i), data=clock)  # compression ...?

            output = self.outputs[i].get_all_outputs()[0]
            if output is None:
                raise LabscriptError("OutputDevice '{}' has no Output connected!".format(self.output_devices[i].name))

            output_data = output.raw_output

            data_group = device_group.create_dataset("data/{}".format(i), data=output_data)  # compression ?

            # store the type of output, we don't really need the digital output data because we just update on tick (but how to know initial state?)
            data_group.attrs['type'] = output.__class__.__name__
            
        # do we need this?
        device_group.attrs['stop_time'] = self.stop_time


class OutputIntermediateDevice(IntermediateDevice):
    """ An intermediate device that connects to some output device. """

    # clock_limit =
    # description = 

    # what sort of outputs are required ?
    allowed_children = [AnalogOut, DigitalOut]

    def __init__(self, name, clock_line):
        IntermediateDevice.__init__(self, name, clock_line)
        self.output = None

    def add_device(self, device):
        """ Disallow adding multiple devices, only allowed child is a single output. """
        if self.child_devices:
            raise LabscriptError("Output '{}' is already connected to the OutputIntermediateDevice '{}'. Only one output is allowed.".format(
                self.child_devices[0].name,  self.name))
        else:
            IntermediateDevice.add_device(self, device)
            self.output = device  # store reference to the output


#########
# BLACS #
#########

from labscript_devices import BLACS_tab, BLACS_worker
from blacs.tab_base_classes import Worker, define_state, \
    MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_BUFFERED, MODE_TRANSITION_TO_MANUAL
from blacs.device_base_class import DeviceTab


@BLACS_tab
class FPGADeviceTab(DeviceTab):

    def initialise_GUI(self):
        dds_widgets, ao_widgets, do_widgets = self.auto_place_widgets()


@BLACS_worker
class FPGADeviceWorker(Worker):
    pass
