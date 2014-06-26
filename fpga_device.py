# skeleton for the FPGA device with multiple pseudoclocks each connected to a single output

from labscript_devices import labscript_device  #, BLACS_tab, BLACS_worker, runviewer_parser

from labscript import PseudoclockDevice, Pseudoclock, ClockLine, IntermediateDevice, Output, \
    LabscriptError  #DigitalQuantity, DigitalOut, DDS, config, LabscriptError

# FPGADevice("", n_outputs, triggers...) ?
# FPGADevice('', [pseudoclocks], [outputs], triggers...) ?

@labscript_device
class FPGADevice(PseudoclockDevice):
    """ device with n indiviually pseudoclocked outputs. """

    description = "FPGA-Device"
    allowed_children = [Pseudoclock]

    def __init__(self, name, n_outputs, trigger_device=None, trigger_connection=None):
        PseudoclockDevice.__init__(self, name, trigger_device, trigger_connection)
        #self.BLACS_connection = board_number

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
            self.outputs.append(OutputIntermediateDevice("fpga_output{}".format(n), cl))
    

    def get_direct_outputs(self):
        """Finds out which outputs are directly attached """
        dig_outputs = []
        dds_outputs = []
        for output in self.direct_outputs.get_all_outputs():
            # If we are a child of a DDS
            if isinstance(output.parent_device, DDS):
                # and that DDS has not been processed yet
                if output.parent_device not in dds_outputs:
                    # process the DDS instead of the child
                    output = output.parent_device
                else:
                    # ignore the child
                    continue
            
            # only check DDS and DigitalOuts (so ignore the children of the DDS)
            if isinstance(output,DDS) or isinstance(output, DigitalOut):
                # get connection number and prefix
                try:
                    prefix, connection = output.connection.split()
                    assert prefix == 'flag' or prefix == 'dds'
                    connection = int(connection)
                except:
                    raise LabscriptError('%s %s has invalid connection string: \'%s\'. '%(output.description,output.name,str(output.connection)) + 
                                         'Format must be \'flag n\' with n an integer less than %d, or \'dds n\' with n less than 2.'%self.n_flags)
                # run checks on the connection string to make sure it is valid
                # TODO: Most of this should be done in add_device() No?
                if prefix == 'flag' and not self.flag_valid(connection):
                    raise LabscriptError('%s is set as connected to flag %d of %s. '%(output.name, connection, self.name) +
                                         'Output flag number must be a integer from 0 to %d.'%(self.n_flags-1))
                if prefix == 'flag' and self.flag_is_clock(connection):
                    raise LabscriptError('%s is set as connected to flag %d of %s.'%(output.name, connection, self.name) +
                                         ' This flag is already in use as one of the PulseBlaster\'s clock flags.')                         
                if prefix == 'dds' and not connection < 2:
                    raise LabscriptError('%s is set as connected to output connection %d of %s. '%(output.name, connection, self.name) +
                                         'DDS output connection number must be a integer less than 2.')
                
                # Check that the connection string doesn't conflict with another output
                for other_output in dig_outputs + dds_outputs:
                    if output.connection == other_output.connection:
                        raise LabscriptError('%s and %s are both set as connected to %s of %s.'%(output.name, other_output.name, output.connection, self.name))
                
                # store a reference to the output
                if isinstance(output, DigitalOut):
                    dig_outputs.append(output)
                elif isinstance(output, DDS):
                    dds_outputs.append(output)
                
        return dig_outputs, dds_outputs

class OutputIntermediateDevice(IntermediateDevice):
    """ An intermediate device that connects to some supplied output device. """
    allowed_children = [Output]
    
    def __init__(self, name, clock_line, output):
        IntermediateDevice.__init__(self, name, clock_line)

