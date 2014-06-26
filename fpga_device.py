# skeleton for the FPGA device with multiple pseudoclocks each connected to a single output

from labscript_devices import labscript_device  #, BLACS_tab, BLACS_worker, runviewer_parser

from labscript import PseudoclockDevice, Pseudoclock, ClockLine, IntermediateDevice, Output, \
    LabscriptError  #DigitalQuantity, DigitalOut, DDS, config, LabscriptError

# class design ?
# FPGADevice('fpga', n_outputs, triggers...)
# fpga.analog_out[0].ramp(...)
# fpga.output('identifier').ramp(...)
#
# FPGADevice('fpga', n_outputs, triggers...)
# FPGAAnalogOut('analog0', fpga, 'ao0')
# analog0.ramp(...)


@labscript_device
class FPGADevice(PseudoclockDevice):
    """ device with n indiviually pseudoclocked outputs. """

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
            pc = Pseudoclock("fpga_pseudoclock{}".format(name), self, "clock_{}".format(n))
            self.pseudoclocks.append(pc)

            # Create the internal direct output clock_line
            # FIXME: do we allow ramping?
            cl = ClockLine("fpga_output{}_clock_line".format(n), pc, "internal", ramping_allowed=False)
            self.clocklines.append(cl)

            # Create the internal intermediate device (outputs) connected to the above clock line
            self.outputs.append(OutputIntermediateDevice("fpga_output_device{}".format(n), cl))


class OutputIntermediateDevice(IntermediateDevice):
    """ An intermediate device that connects to some output device. """

    # clock_limit =
    # description = 

    # FIXME: be more restrictive?
    allowed_children = [Output]

    def __init__(self, name, clock_line, output):
        IntermediateDevice.__init__(self, name, clock_line)
        self.output = Output(name.replace("_device",''), self, name.replace("device", "connection")

    # disallow adding devices?
    # def add_device(...):
