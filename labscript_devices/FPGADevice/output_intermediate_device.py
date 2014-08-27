from labscript import IntermediateDevice, LabscriptError
from fpga_outputs import FPGAAnalogOut, FPGADigitalOut

class OutputIntermediateDevice(IntermediateDevice):
    """ An intermediate device that connects to some output device. """

    allowed_children = [FPGAAnalogOut, FPGADigitalOut]

    def __init__(self, name, clock_line):
        IntermediateDevice.__init__(self, name, clock_line)
        self.output = None

    def add_device(self, device):
        """ Disallow adding multiple devices, only allowed child is a single output.
            Also restrict connection names (BLACS code expects specific names). """

        # disallow adding multiple devices
        if self.child_devices:
            raise LabscriptError("Output '{}' is already connected to the OutputIntermediateDevice '{}'."
                                 "Only one output is allowed.".format(self.child_devices[0].name, self.name))
        else:
            IntermediateDevice.add_device(self, device)
            self.output = device  # store reference to the output
