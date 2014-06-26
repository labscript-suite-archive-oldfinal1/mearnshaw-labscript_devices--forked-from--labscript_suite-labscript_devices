# skeleton for the FPGA device with multiple pseudoclocks each connected to a single output

from labscript_devices import labscript_device  #, BLACS_tab, BLACS_worker, runviewer_parser

from labscript import PseudoclockDevice, Pseudoclock, ClockLine, IntermediateDevice, Output, \
    LabscriptError  #DigitalQuantity, DigitalOut, DDS, config, LabscriptError

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

    def __init__(self, name, n_outputs, trigger_device=None, trigger_connection=None):
        PseudoclockDevice.__init__(self, name, trigger_device, trigger_connection)
        # self.BLACS_connection = board_number

        self.pseudoclocks = []
        self.clocklines = []
        self.outputs = []
        # Create the internal pseudoclocks and clocklines, and the outputs
        for n in range(n_outputs):
            pc = Pseudoclock("fpga_pseudoclock{}".format(n), self, "clock_{}".format(n))
            self.pseudoclocks.append(pc)

            # Create the internal direct output clock_line
            cl = ClockLine("fpga_output{}_clock_line".format(n), pc, "fpga_internal{}".format(n))
            self.clocklines.append(cl)

            # Create the internal intermediate device (outputs) connected to the above clock line
            # use OutputIntermediateDevice to limit no. outputs that can be connected?
            self.outputs.append(OutputIntermediateDevice("fpga_output_device{}".format(n), cl))


class OutputIntermediateDevice(IntermediateDevice):
    """ An intermediate device that connects to some output device. """

    # clock_limit =
    # description = 

    # be more restrictive?
    allowed_children = [Output]

    def __init__(self, name, clock_line):
        IntermediateDevice.__init__(self, name, clock_line)

    # disallow adding multiple devices?
    # def add_device(...):
