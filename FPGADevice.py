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
# FPGADevice(name='fpga', usb_port='COM1')
# AnalogOut('analog0', fpga.outputs, 'ao0')
# DigitalOut('digi0', fpga.outputs, 'digi1')
#
# start()
# analog0.ramp(0, duration=3, initial=0, final=1, samplerate=1e4)
# stop(1)


def convert_to_clocks_and_toggles(clock, output, clock_limit, clock_resolution):
    """ Given a list of step/reps dictionaries 
    (as returned in .clock by Pseudoclock.generate_code),
    return list of clocks/toggles dictionaries (see below)

    n_clocks: some number of clock cycles
    toggles: number of times to change clock during this number of cycles
    """
    ct_clock = []

    for i, tick in enumerate(clock):

        # For digital outputs, the first (toggles)/(clocks)
        # specifies (the inital state)/(# clocks to hold it for)
        # NB. n_clocks=n => wait n-1 clock cycles before toggling
        if i == 0 and isinstance(output, DigitalOut):
            initial_state = output.raw_output[0]
            period = int(round(tick['step'] / clock_resolution)) * clock_resolution
            n_clocks = (period / clock_limit) - 1
            ct_clock.append({'n_clocks': n_clocks, 'toggles': initial_state})
            tick['reps'] -= 1  # have essentially dealt with 1 rep above

        period = int(round(tick['step'] / clock_resolution)) * clock_resolution
        toggles = tick['reps']
        n_clocks = (period * clock_limit) - 1
        ct_clock.append({'n_clocks': n_clocks, 'toggles': toggles})

    return ct_clock


@labscript_device
class FPGADevice(PseudoclockDevice):
    """ A device with indiviually pseudoclocked outputs. """

    clock_limit = 10e6  # true value??
    clock_resolution = 1e-9  # true value??

    description = "FPGA-Device"
    allowed_children = [Pseudoclock]

    def __init__(self, name, usb_port, max_outputs=None, trigger_device=None, trigger_connection=None):
        PseudoclockDevice.__init__(self, name, trigger_device, trigger_connection)

        self.BLACS_connection = usb_port

        self.max_outputs = max_outputs

        self.pseudoclocks = []
        self.clocklines = []
        self.output_devices = []

    # restrict devices here?
    #def add_device(...):

    @property
    def outputs(self):
        """ Return an output device to which an output can be connected. """
        n = len(self.pseudoclocks)  # the number identifying this new output (zero indexed)

        if n == self.max_outputs:
            raise LabscriptError("Cannot connect more than {} outputs to the device '{}'".format(n, self.name))
        else:
            pc = Pseudoclock("fpga_pseudoclock{}".format(n), self, "clock_{}".format(n))
            self.pseudoclocks.append(pc)

            # Create the internal direct output clock_line
            cl = ClockLine("fpga_output{}_clock_line".format(n), pc, "fpga_internal{}".format(n))
            # do we really need to store the list of clocklines?
            self.clocklines.append(cl)

            # Create the internal intermediate device (outputs) connected to the above clock line
            oid = OutputIntermediateDevice("fpga_output_device{}".format(n), cl)
            self.output_devices.append(oid)
            return oid

    def generate_code(self, hdf5_file):
        PseudoclockDevice.generate_code(self, hdf5_file)

        # group in which to save instructions for this device
        device_group = hdf5_file.create_group("/devices/{}".format(self.name))

        # reduce instructions?
        for i, pseudoclock in enumerate(self.pseudoclocks):

            output = self.output_devices[i].get_all_outputs()[0]  # improve the class API to make this nicer?

            # this check might not be necessary, this condition shouldn't occur in any normal usage
            if output is None:
                raise LabscriptError("OutputDevice '{}' has no Output connected!".format(self.output_devices[i].name))

            # process the clock
            ct_clock = convert_to_clocks_and_toggles(pseudoclock.clock, output, self.clock_limit, self.clock_resolution)
            clock = np.zeros(len(ct_clock), dtype=[('n_clocks', int), ('toggles', int)])
            #clock = np.zeros(len(pseudoclock.clock), dtype=[('period', int), ('reps', int)])

            for j, tick in enumerate(ct_clock):
                clock[j]['n_clocks'] = tick['n_clocks']
                clock[j]['toggles'] = tick['toggles']

            device_group.create_dataset("clocks/{}".format(output.name), data=clock)  # compression ...?

            """
            ### Period and reps clocks ###
            pr_clock = np.zeros(len(pseudoclock.clock), dtype=[('period', int), ('reps', int)])
            for j, tick in enumerate(pseudoclock.clock):
                period = int(round(tick['step'] / self.clock_resolution))
                pr_clock[j]['period'] = period
                pr_clock[j]['reps'] = tick['reps']

            device_group.create_dataset("pr_clocks/{}".format(output.name), data=pr_clock)  # compression ...?
            """

        # we only need to save analog data, digital outputs are updated directly by clocking signal
        if isinstance(output, AnalogOut):
            analog_data = output.raw_output
            device_group.create_dataset("analog_data/{}".format(output.name), data=analog_data)  # compression ?

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
                self.child_devices[0].name, self.name))
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
