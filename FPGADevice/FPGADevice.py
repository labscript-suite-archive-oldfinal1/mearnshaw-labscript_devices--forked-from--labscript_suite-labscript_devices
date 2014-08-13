"""A device with indiviually pseudoclocked outputs."""

from labscript_devices import labscript_device, BLACS_tab, BLACS_worker, runviewer_parser

from labscript_devices.FPGADevice.output_connection_name import OutputConnectionName
from labscript_devices.FPGADevice.output_intermediate_device import OutputIntermediateDevice
from labscript_devices.FPGADevice.fpga_widgets_style import DO_style
from labscript_devices.FPGADevice.fpga_outputs import FPGAAnalogOut, FPGADigitalOut
from labscript_devices.FPGADevice.clock_processing import *
from labscript_devices.FPGADevice.util import *

from labscript import PseudoclockDevice, Pseudoclock, ClockLine, IntermediateDevice,\
    AnalogOut, DigitalOut, LabscriptError, config

from labscript import labscript

from blacs.tab_base_classes import Worker, define_state, \
    MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_BUFFERED, MODE_TRANSITION_TO_MANUAL
from blacs.device_base_class import DeviceTab
from blacs.connections import ConnectionTable

from PySide.QtCore import Qt, Slot
from PySide.QtGui import QHBoxLayout, QWidget, QComboBox, QLabel, QVBoxLayout, QGroupBox
from labscript_utils.qtwidgets.toolpalette import ToolPaletteGroup

import numpy as np
import h5py
import logging
import functools
import re

clocks_chunksize = 256
clocks_delay = 0.01

data_chunksize = 4
data_delay = None #0.005

logger = logging.getLogger("main")

# Example
#
# import __init__ # only have to do this because we're inside the labscript directory
# from labscript import *
# from labscript_devices.FPGADevice import FPGADevice
#
# FPGADevice(name='fpga')
# AnalogOut('analog0', fpga.outputs, 'analog 0')
# DigitalOut('digi0', fpga.outputs, 'digital 1')
#
# start()
# analog0.ramp(0, duration=3, initial=0, final=1, samplerate=1e4)
# stop(1)


@labscript_device
class FPGADevice(PseudoclockDevice):
    """ A device with indiviually pseudoclocked outputs. """
    max_clock_instructions = 255  # max number of pairs of p/r or c/t per channel
    max_analog_data = 2**16 - 1  # max number of words for the analog channels

    clock_limit = 30e6  # 30 MHz
    clock_resolution = 1000.0 / clock_limit

    description = "FPGA-Device"
    allowed_children = [Pseudoclock, DigitalOut]

    def __init__(self, name, n_analog=None, n_digital=None):
        """ n_analog: number of analog outputs expected (optional, unlimited if unspecified)
            n_digital: number of digital outputs expected (optional, unlimited if unspecified)
        """
        PseudoclockDevice.__init__(self, name)

        self.BLACS_connection = None

        # number of outputs of each type that device should have, if specified
        self.n_analog = n_analog
        self.n_digital = n_digital

        self.analog_channel_numbers = set(range(8))  # 0-7
        self.digital_channel_numbers = set(range(8, 34))  # 8-33

        self.pseudoclocks = []
        self.clocklines = []
        self.output_devices = []
        self.waits = []
        self.wait_times = []

    @property
    def outputs(self):
        """ Return an output device to which an output can be connected. """
        n = len(self.pseudoclocks)  # the number identifying this new output (zero indexed)

        try:
            max_n = self.n_digital + self.n_analog
        except TypeError:
            max_n = None  # if neither specified

        if n == max_n:
            raise LabscriptError("Cannot connect more than {} outputs to the device '{}'".format(n, self.name))
        else:
            pc = Pseudoclock("{}_pseudoclock{}".format(self.name, n), self, "{}_clock_{}".format(self.name, n))
            self.pseudoclocks.append(pc)

            # Create the internal direct output clock_line
            cl = ClockLine("{}_output{}_clock_line".format(self.name, n), pc, "{}_internal{}".format(self.name, n))
            # FIXME: do we really need to store the list of clocklines?
            self.clocklines.append(cl)

            # Create the internal intermediate device (outputs) connected to the above clock line
            oid = OutputIntermediateDevice("{}_output_device{}".format(self.name, n), cl)
            self.output_devices.append(oid)
            return oid

    def trigger(self, t, duration, wait_delay=0):
        """Ask the trigger device to produce a digital pulse of a given duration to trigger this pseudoclock.
           We override this method here to remove the checking for WaitMonitor, we don't require one."""
        if t == 'initial':
            t = self.initial_trigger_time
        t = round(t, 10)
        if self.is_master_pseudoclock:
            # FIXME: do we need this pulse?
            # Make the wait monitor pulse to signify starting or resumption of the experiment:
            # labscript.compiler.wait_monitor.trigger(t, duration)
            self.trigger_times.append(t)
        else:
            self.trigger_device.trigger(t, duration)
            self.trigger_times.append(round(t + wait_delay, 10))

    def wait(self, at_time, board_number=None, channel_number=None, value=None, comparison=None):
        # ensure we have an entry in the labscript compiler wait table
        self.wait_times.append(at_time * self.clock_limit)
        # labscript.wait(label='wait{}'.format(len(self.waits)), t=at_time, timeout=5)
        self.waits.append(FPGAWait(board_number, channel_number, value, comparison))
        # FIXME: return a time!

    def generate_code(self, hdf5_file):
        # check that correct number of outputs are attached
        outputs = [output_device.output.__class__ for output_device in self.output_devices]

        used_channels = set([OutputConnectionName.channel_number(output_device.output.connection)
                             for output_device in self.output_devices])

        n_analog = outputs.count(FPGAAnalogOut)
        n_digital = outputs.count(FPGADigitalOut)

        """
        # expected number not specified => whatever we have is correct
        if not self.n_digital:
            self.n_digital = n_digital
        if not self.n_analog:
            self.n_analog = n_analog

        if (self.n_analog != n_analog) or (self.n_digital != n_digital):
            raise LabscriptError("FPGADevice '{}' does not have enough outputs attached. "
                                 "Expected {} digital, {} analog but found {} digital, {} analog".format(self.name,
                                                                                                         self.n_digital, self.n_analog,
                                                                                                         n_digital, n_analog))
        """
        
        if self.n_digital or self.n_analog:
            # create constant outputs on unused channels
            # FIXME: remove hardcoded board number
            for n in self.analog_channel_numbers.difference(used_channels):
                FPGAAnalogOut("_analog_placeholder{}".format(n), self.outputs, board_number=1, channel_number=n, group_name="placeholder")

            for n in self.digital_channel_numbers.difference(used_channels):
                FPGADigitalOut("_digital_placeholder{}".format(n), self.outputs, board_number=1, channel_number=n, group_name="placeholder")

        PseudoclockDevice.generate_code(self, hdf5_file)

        # group in which to save instructions for this device
        device_group = hdf5_file.create_group("/devices/{}".format(self.name))

        # create subgroups for the clocks, analog data, and analog limits
        clock_group = device_group.create_group("clocks")
        analog_data_group = device_group.create_group("analog_data")
        analog_limits_group = device_group.create_group("analog_limits")
        waits_group = device_group.create_group("waits")
        wait_times_group = device_group.create_group("wait_times")

        # FIXME: inefficient/unclear to have to reprocess the data structure here
        for i, wait in enumerate(self.waits):
            wait = wait.__dict__
            dtype = [(wait.keys()[i], type(wait.values()[i])) for i in range(4)]
            wait = np.array(tuple(wait.values()), dtype=dtype)
            waits_group.create_dataset("wait{}".format(i), data=wait, compression=config.compression)

        for i, wait in enumerate(self.wait_times):
            wait_times = np.array(self.wait_times, dtype=float)
            wait_times_group.create_dataset("wait_times", data=wait_times, compression=config.compression)

        for i, pseudoclock in enumerate(self.pseudoclocks):
            output = self.output_devices[i].output
            output_connection = output.connection

            if output is None:
                raise LabscriptError("OutputDevice '{}' has no Output connected!".format(output.name))

            # combine instructions with equal periods
            pseudoclock.clock = reduce_clock_instructions(pseudoclock.clock)  # , self.clock_resolution)

            # for digital outs, change from period/reps system to clocks/toggles (see function for explanation)
            if isinstance(output, FPGADigitalOut):
                pseudoclock.clock = convert_to_clocks_and_toggles(pseudoclock.clock, output, self.clock_limit)  # , self.clock_resolution)
                clock_dtype = [('n_clocks', int), ('toggles', int)]
            else:
                # for other outputs (analog) we just use the period/reps form.

                # pack values into a data structure from which we can initialize an np array directly
                pseudoclock.clock = process_analog_clock(pseudoclock.clock, self.clock_limit)
                clock_dtype = [('period', int), ('reps', int)]

            if len(pseudoclock.clock) > self.max_clock_instructions:
                raise LabscriptError("Cannot exceed more than {} clock"
                                     "instructions per channel ({} requested)".format(self.max_clock_instructions, len(pseudoclock.clock)))

            # FIXME: find a proper way to deal with ghost instructions generated by labscript even when none specified
            #elif len(pseudoclock.clock) == 2:
            #    print pseudoclock.clock
            #    continue

            clock = np.array(pseudoclock.clock, dtype=clock_dtype)

            clock_group.create_dataset(output_connection,
                                       data=clock,
                                       compression=config.compression)

            #clock_group[output_connection].attrs['board_number'] = output.board_number

            # we only need to save analog data, digital outputs are
            # constructed from the clocks/toggles clocking signal
            if isinstance(output, FPGAAnalogOut):
                if len(output.raw_output) > self.max_analog_data:
                    raise LabscriptError("Cannot exceed more than {} analog data"
                                         "points per channel ({} requested)".format(self.max_analog_data, len(output.raw_output)))
                # labscript gives zero data even if no instructions specified, so ignore these
                #elif not any(output.raw_output):
                #    continue
                else:
                    # FIXME:
                    #output.raw_output = np.append(output.raw_output, [output.raw_output[-1]] * (len(clock)))
                    try:
                        n_reps = sum(clock['reps'])
                    except KeyError:
                        pass

                    #print "n data points: {}, sum(reps): {}, sum(reps)+n_instructions: {}".format(len(output.raw_output), n_reps, n_reps + len(clock))

                    analog_data_group.create_dataset(output_connection,
                                                     data=output.raw_output,
                                                     compression=config.compression)

                # also save the limits of the output
                try:
                    limits = np.array(output.limits, dtype=[('range_min', float), ('range_max', float)])
                    analog_limits_group.create_dataset(output_connection,
                                                       data=limits,
                                                       compression=config.compression)
                except TypeError:
                    # no limits specified
                    pass

        device_group.attrs['stop_time'] = self.stop_time
        device_group.attrs['clock_limit'] = self.clock_limit
        device_group.attrs['clock_resolution'] = self.clock_resolution



#########
# BLACS #
#########


@BLACS_tab
class FPGADeviceTab(DeviceTab):

    def initialise_GUI(self):

        # FIXME: add these
        self.base_units = 'V'
        # self.base_min
        # self.base_max
        # self.base_step
        # self.base_decimals

        output_names = get_output_port_names(self.connection_table, self.device_name)
        self.digital_properties = {}
        self.analog_properties = {}

        # properties['base_unit'], properties['min'], properties['max'], properties['step'], properties['decimals']
        for name, conn_name in output_names:

            group_name = OutputConnectionName.group_name(conn_name)
            # skip any placeholder constant outputs, we don't want to see them in the GUI
            if group_name == "placeholder":
                continue

            output_type = OutputConnectionName.output_type(conn_name)
            if output_type == "analog":
                # FIXME: make sure this min/max works when limits specified in script
                self.analog_properties[name] = {'conn_name': conn_name,
                                                'base_unit': self.base_units,
                                                'min': 0.0, 'max': 5.0, 'step': 0.1, 'decimals': 3}
            elif output_type == "digital":
                self.digital_properties[name] = {'conn_name': conn_name}

        self.create_analog_outputs(self.analog_properties)
        self.create_digital_outputs(self.digital_properties)
        self.DDS_widgets, self.AO_widgets, self.DO_widgets = self.auto_create_widgets()

        self.style_widgets(self.AO_widgets, self.DO_widgets)
        self.auto_place_widgets(self.AO_widgets, self.DO_widgets)

        self.supports_smart_programming(True)

        layout = self.get_tab_layout()
        if self.analog_properties:
            # FIXME: make this robust...
            tp = layout.itemAt(0).widget().children()[0].append_new_palette("DAC Output Ranges") #.parent().parent().append_new_palette("Test")

            self.DAC_ranges = [(0, 5), (0, 10), (-5, 5), (-10, 10), (-2.5, 2.5), (-2.5, 7.5)]

            self.comboboxes = []
            for analog_output in self.analog_properties:
                dac_range_layout = QVBoxLayout()
                parameter_widget = QGroupBox(analog_output)
                parameter_widget.setLayout(dac_range_layout)

                combobox = QComboBox()  #dac_range_widget.DACRangeComboBox
                self.comboboxes.append(combobox)

                for i, DAC_range in enumerate(self.DAC_ranges):
                    combobox.addItem("{} to {} V".format(DAC_range[0], DAC_range[1]))
                dac_range_layout.addWidget(combobox)
                tp.insertWidget(0, parameter_widget)

                conn_name = self.analog_properties[analog_output]['conn_name']
                combobox.currentIndexChanged.connect(functools.partial(self.combo_slot, analog_output, conn_name))

                #dac_range_widget.OutputName.setText(analog_output)

    @Slot(int)
    @define_state(MODE_MANUAL | MODE_BUFFERED | MODE_TRANSITION_TO_BUFFERED | MODE_TRANSITION_TO_MANUAL, True)
    def combo_slot(self, output_name, conn_name, index):
        board_number = OutputConnectionName.board_number(conn_name)
        channel_number = OutputConnectionName.channel_number(conn_name)
        range_min, range_max = self.DAC_ranges[index]
        self.analog_properties[output_name]['min'] = range_min
        self.analog_properties[output_name]['max'] = range_max
        self.AO_widgets[output_name].set_limits(range_min, range_max)
        yield(self.queue_work(self.primary_worker, "update_output_properties", self.analog_properties, self.digital_properties))
        yield(self.queue_work(self.primary_worker, "send_output_range", board_number, channel_number, index))

    def style_widgets(self, AO_widgets, DO_widgets):
        """ Apply stylesheets to widgets. """
        for output_name in DO_widgets:
            DO_widgets[output_name].setStyleSheet(DO_style)

    def initialise_workers(self):
        initial_values = self.get_front_panel_values()
        # pass initial front panel values to worker for manual programming cache

        self.create_worker("main_worker", FPGADeviceWorker, {
                           'initial_values': initial_values,
                           'analog_properties': self.analog_properties,
                           'digital_properties': self.digital_properties,
                           }
                           )
        self.primary_worker = "main_worker"

        # FIXME: instatiate this worker only if we have waits
        # worker to acquire input values in real time for use in wait conditions
        # self.create_worker("acquisition_worker", AcquisitionWorker)
        # self.add_secondary_worker("acquisition_worker")

    def get_child_from_connection_table(self, parent_device_name, port):
        """ Return connection object for the output connected to an IntermediateDevice via the port specified. """

        if parent_device_name == self.device_name:
            device_conn = self.connection_table.find_by_name(self.device_name)

            pseudoclocks_conn = device_conn.child_list  # children of our pseudoclock device are just the pseudoclocks

            for pseudoclock_conn in pseudoclocks_conn.values():
                clockline_conn = pseudoclock_conn.child_list.values()[0]  # each pseudoclock has 1 child, a clockline
                intermediate_device_conn = clockline_conn.child_list.values()[0]  # each clock line has 1 child, an intermediate device

                if intermediate_device_conn.parent_port == port:
                    return intermediate_device_conn
        else:
            # else it's a child of a DDS, so we can use the default behaviour to find the device
            return DeviceTab.get_child_from_connection_table(self, parent_device_name, port)

    @define_state(MODE_MANUAL | MODE_BUFFERED | MODE_TRANSITION_TO_BUFFERED | MODE_TRANSITION_TO_MANUAL, True)
    def status_monitor(self, notify_queue=None):
        """ Get status of FPGA and update the widgets in BLACS accordingly. """
        # When called with a queue, this function writes to the queue
        # when the FPGA is waiting. This indicates the end of
        # an experimental run.
        self.status = yield(self.queue_work(self.primary_worker, 'check_status'))

        # FIXME: use FPGAStates.shot_finished instead of '\x07', but avoid import dep. issue
        if notify_queue is not None and self.status == '\x07':
            # Experiment is over. Tell the queue manager about it, then
            # set the status checking timeout back to every 2 seconds
            # with no queue.
            notify_queue.put('done')
            self.statemachine_timeout_remove(self.status_monitor)
            self.statemachine_timeout_add(2000, self.status_monitor)

        # TODO: Update widgets
        # a = ['stopped','reset','running','waiting']
        # for name in a:
            # if self.status[name] == True:
                # self.status_widgets[name+'_no'].hide()
                # self.status_widgets[name+'_yes'].show()
            # else:                
                # self.status_widgets[name+'_no'].show()
                # self.status_widgets[name+'_yes'].hide()

    @define_state(MODE_MANUAL | MODE_BUFFERED | MODE_TRANSITION_TO_BUFFERED | MODE_TRANSITION_TO_MANUAL, True)
    def start(self, widget=None):
        yield(self.queue_work(self.primary_worker, 'start'))
        self.status_monitor()

    @define_state(MODE_MANUAL | MODE_BUFFERED | MODE_TRANSITION_TO_BUFFERED | MODE_TRANSITION_TO_MANUAL, True)
    def stop(self, widget=None):
        yield(self.queue_work(self.primary_worker, 'stop'))
        self.status_monitor()

    @define_state(MODE_MANUAL | MODE_BUFFERED | MODE_TRANSITION_TO_BUFFERED | MODE_TRANSITION_TO_MANUAL, True)
    def reset(self, widget=None):
        yield(self.queue_work(self.primary_worker, 'reset'))
        self.status_monitor()

    @define_state(MODE_BUFFERED, True)
    def start_run(self, notify_queue):
        """ function called by Queue Manager to begin a buffered shot. """
        # stop monitoring the device status
        self.statemachine_timeout_remove(self.status_monitor)
        # start the shot
        logger.debug("i.start()")
        self.start()
        # poll status every 100ms to notify Queue Manager at end of shot
        self.statemachine_timeout_add(100, self.status_monitor, notify_queue)


@BLACS_worker
class FPGADeviceWorker(Worker):

    def init(self):
        # do imports here otherwise "they will be imported in both the parent and child
        # processes and won't be cleanly restarted when the subprocess is restarted."
        from labscript_devices.FPGADevice.fpga_api import FPGAInterface, FTDIError

        # FIXME: remove this try/except
        try:
            self.interface = FPGAInterface()
        except FTDIError:
            self.interface = FPGAInterface(0x0403, 0x6001)
            
        # define these aliases so that the DeviceTab class can see them
        self.start = self.interface.start
        self.stop = self.interface.stop
        self.reset = self.interface.reset
        self.send_parameter = self.interface.send_parameter
        self.send_output_range = self.interface.send_output_range

        # cache for smart programming
        # initial_values attr is created by the DeviceTab initialise_workers method
        # and reflects the initial state of the front panel values for manual_program to inspect
        self.smart_cache = {'clocks': {}, 'data': {}, 'output_values': self.initial_values}

    def update_output_properties(self, analog_properties, digital_properties):
        self.analog_properties = analog_properties
        self.digital_properties = digital_properties

    def check_status(self):
        # return '\x07'
        return self.interface.check_status()

    def program_manual(self, values):
        """ Program device to output values when not executing a buffered shot, ie. realtime mode. """
        
        modified_values = {}

        for output_name in values:
            value = values[output_name]

            # only update output if it has changed
            if value != self.smart_cache['output_values'].get(output_name):
                try:
                    conn_name = self.analog_properties[output_name]['conn_name']
                except KeyError:
                    conn_name = self.digital_properties[output_name]['conn_name']

                output_type, board_number, channel_number, group_name = OutputConnectionName.decode(conn_name)

                # FIXME: clarify this logic, better not to send range at all if we have digi
                if output_type == "analog":
                    range_min, range_max = self.analog_properties[output_name]['min'], self.analog_properties[output_name]['max']
                else:
                    # we have a digital out or a placeholder so range is whatever
                    range_min, range_max = 0, 5

                logger.debug("i.send_realtime_value(board_number={}, channel_number={}, "
                             "value={}, range_min={}, range_max={}, output_type={})".format(board_number, channel_number, value, range_min, range_max, output_type))

                # the value sent to the board may be coerced/quantized from the one requested
                # send_realtime_value returns the actual value the board is now outputting
                # so we can update the front panel to accurately reflect this
                new_value = self.interface.send_realtime_value(board_number, channel_number, value, range_min, range_max, output_type)
                modified_values[output_name] = new_value
                self.smart_cache['output_values'][output_name] = new_value

        self.interface.send_buffer()
        return modified_values

    def transition_to_buffered(self, device_name, h5file, initial_values, fresh_program):
        """  This function is called whenever the Queue Manager requests the
        device to move into buffered mode in preparation for executing a buffered sequence. """

        with h5py.File(h5file, 'r') as hdf5_file:
            device_group = hdf5_file['devices'][device_name]

            clocks = device_group['clocks']
            analog_data = device_group['analog_data']
            limits = device_group['analog_limits']
            waits = device_group['waits']
            wait_times = device_group['wait_times']

            clock_limit = device_group.attrs['clock_limit']
            stop_time = device_group.attrs['stop_time']

            # value of each output at end of shot
            final_state = {}

            # send repeats/period
            # shot_period = 2 * sum([(tick['reps']+1)*(tick['period']+1) for tick in clocks[clocks.keys()[0]]])
            shot_period = int(stop_time * clock_limit)

            # FIXME: this is a bit messy, can we just save the value at compile time?
            try:
                # try to extract shot_reps variable from script
                shot_reps = int(re.search(r"shot_reps[ ]*=[ ]*([0-9]+)", hdf5_file['script'].value).group(1))
            except AttributeError:
                shot_reps = 1

            logger.debug("i.send_repeats_and_period(shot_reps={}, shot_period={})".format(shot_reps, shot_period))
            self.interface.send_repeats_and_period(shot_reps, shot_period)

            # send the pseudoclocks

            for i, output in enumerate(clocks):
                clock = clocks[output].value

                output_type, board_number, channel_number, group_name = OutputConnectionName.decode(output)

                # get the name of the output corresponding to the output channel name
                if group_name != "placeholder":
                    if output_type == "analog":
                        output_name = filter(lambda x: x[1] == output, [(x, y['conn_name']) for x, y in self.analog_properties.items()])[0][0]
                    elif output_type == "digital":
                        output_name = filter(lambda x: x[1] == output, [(x, y['conn_name']) for x, y in self.digital_properties.items()])[0][0]
                else:
                    # placeholder outputs aren't listed in analog_properties, 
                    # and they aren't a concern for smart programmng anyway as they're constant
                    output_name = "placeholder"

                # only send if it has changed or fresh program is requested
                if fresh_program or np.any(clock != self.smart_cache['clocks'].get(output)):
                    self.smart_cache['clocks'][output] = clock
                    logger.debug("i.send_pseudoclock(board_number={}, channel_number={}, clock={})".format(board_number, channel_number, clock))
                    self.interface.send_pseudoclock(board_number, channel_number, clock=clock)

                if output_type == "digital":
                    # then determine what the final state of the digital out is (initial state + n_toggles mod 2)
                    n_toggles = sum(clock['toggles'])
                    final_state[output_name] = clock[0]['toggles'] + (n_toggles % 2)

            # FIXME: remove
            self.interface.send_buffer(clocks_chunksize, clocks_delay)

            # send the analog data
            for i, output in enumerate(analog_data):

   
                data = analog_data[output].value
                # only send if it has changed or fresh program is requested
                if fresh_program or np.any(data != self.smart_cache['data'].get(output)):

                    # FIXME: duplicated from above
                    output_type, board_number, channel_number, group_name = OutputConnectionName.decode(output)

                    # get the name of the output corresponding to the output channel name
                    if group_name != "placeholder":
                        if output_type == "analog":
                            output_name = filter(lambda x: x[1] == output, [(x, y['conn_name']) for x, y in self.analog_properties.items()])[0][0]
                        elif output_type == "digital":
                            output_name = filter(lambda x: x[1] == output, [(x, y['conn_name']) for x, y in self.digital_properties.items()])[0][0]
                    else:
                        # placeholder outputs aren't listed in analog_properties, 
                        # and they aren't a concern for smart programmng anyway as they're constant
                        output_name = "placeholder"


                    final_state[output_name] = data[-1]
                    self.smart_cache['data'][output] = data
    
                    # FIXME: better not to send range at all for digi
                    try:
                        range_min, range_max = self.analog_properties[output_name]['min'], self.analog_properties[output_name]['max']
                    except KeyError:
                        range_min, range_max = 0, 5

                    output_type, board_number, channel_number, group_name = OutputConnectionName.decode(output)
                    logger.debug("i.send_analog_data(board_number={}, channel_number={}, "
                                 "range_min={}, range_max={}, data={})".format(board_number, channel_number, range_min, range_max, data))
                    self.interface.send_analog_data(board_number, channel_number, range_min, range_max, data)

            # FIXME: remove
            self.interface.send_buffer(data_chunksize, data_delay)

            # send the waits
            for i, wait in enumerate(waits):
                wait = waits[wait].value
                logger.debug("i.send_wait_info(board_number={}, channel_number={}, "
                             "value={}, comparison={})".format(wait['board_number'], wait['channel_number'], wait['value'], wait['comparison']))
                self.interface.send_wait_info(wait['board_number'], wait['channel_number'], wait['value'], wait['comparison'])

            # send wait times
            try:
                logger.debug("i.send_wait_times(wait_times={})".format(wait_times['wait_times'].value))
                self.interface.send_wait_times(wait_times['wait_times'].value)
            except KeyError:
                # no wait times
                pass

        self.interface.send_buffer()
        return final_state

    def transition_to_manual(self):
        """ This function is called after the master pseudoclock reports that the experiment has finished.
        This function takes no arguments, should place the device back in the correct mode for operation
        by the front panel of BLACS, and return a Boolean flag indicating the success of this method. """
        # FIXME: implement, if required - DeviceTab implementation may be sufficient.
        return True

    def abort_buffered(self):
        # FIXME: implement, if required - DeviceTab implementation may be sufficient.
        # place the device back in manual mode, while in the middle
        # of an experiment shot
        # return True if this was all successful, or False otherwise
        return True

    def abort_transition_to_buffered(self):
        # FIXME: implement, if required - DeviceTab implementation may be sufficient.
        # place the device back in manual mode, after the device has run
        # transition_to_buffered, but has not been triggered to
        # begin the experiment shot.
        # return True if this was all successful, or False otherwise
        return True

    def shutdown(self):
        # This should put the device in safe state, for example closing any open communication connections with the device.
        # The function should not return any value (the return value is ignored)
        pass


@runviewer_parser
class FPGARunViewerParser:

    def __init__(self, path, device):
        self.path = path
        self.device_name = device.name
        self.device = device

        with h5py.File(self.path, 'r') as f:
            self.stop_time = f['devices'][self.device_name].attrs['stop_time']
            self.clock_limit = f['devices'][self.device_name].attrs['clock_limit']
            #self.clock_resolution = f['devices'][self.device_name].attrs['clock_resolution']

        connection_table = ConnectionTable(path)
        self.output_port_names = [i[1] for i in get_output_port_names(connection_table, self.device_name)]

    def get_traces(self, add_trace, clock=None):
        with h5py.File(self.path, 'r') as f:
            clocks_group = f['devices'][self.device_name]['clocks']
            analog_data_group = f['devices'][self.device_name]['analog_data']

            for output_name in clocks_group:
                # expand clocks & toggles to a list of times when a clock out occurs
                change_times = expand_clock(clocks_group[output_name], self.clock_limit, self.stop_time)
                if "analog" in output_name:
                    data = analog_data_group[output_name].value
                elif "digital" in output_name:
                    # digital outs always have some state from t=0
                    change_times = [0] + change_times
                    # number of toggles in first instruction gives the initial state
                    initial_state = clocks_group[output_name][0]["toggles"]
                    # generate sequence of 0s and 1s starting on the initial state, for each change time
                    data = [(initial_state + i) % 2 for i in range(len(change_times))]

                # FIXME: add meaningful last values
                add_trace(output_name, (change_times, data), '', '')

        # FIXME: return clocklines_and_triggers (why?)
        return {}


