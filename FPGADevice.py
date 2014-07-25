# skeleton for the FPGA device with multiple pseudoclocks each connected to a single output

from labscript_devices import fpga_widgets_style, labscript_device, BLACS_tab, BLACS_worker, runviewer_parser

from labscript import PseudoclockDevice, Pseudoclock, ClockLine, IntermediateDevice,\
    AnalogOut, DigitalOut, LabscriptError, config

from labscript import labscript

from blacs.tab_base_classes import Worker, define_state, \
    MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_BUFFERED, MODE_TRANSITION_TO_MANUAL
from blacs.device_base_class import DeviceTab
from blacs.connections import ConnectionTable

from PySide.QtUiTools import QUiLoader
from PySide.QtCore import Qt, Slot
from PySide.QtGui import QHBoxLayout, QWidget, QComboBox, QLabel, QVBoxLayout, QGroupBox
from labscript_utils.qtwidgets.toolpalette import ToolPaletteGroup


import numpy as np
import h5py

import collections


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


def reduce_clock_instructions(clock):  # FIXME: clock_resolution?
    """ Combine consecutive instructions with the same period. """

    reduced_instructions = []
    for instruction in clock:
        if instruction == 'WAIT':
            # The following period and reps indicates a wait instruction
            reduced_instructions.append({'step': 0, 'reps': 0})
            continue
        reps = instruction['reps']
        step = instruction['step']
        # see if previous instruction has same 'step' (period) as current
        if reduced_instructions and (reduced_instructions[-1]['step'] == step):
            reduced_instructions[-1]['reps'] += reps
        else:
            reduced_instructions.append({'step': step, 'reps': reps})
    # add stop instruction
    return reduced_instructions


def convert_to_clocks_and_toggles(clock, output, clock_limit):
    """ Given a list of step/reps dictionaries
    (as returned in .clock by Pseudoclock.generate_code),
    return list of (clocks, toggles) tuples (see below)

    The shortest pulse that can be generated by the step(period)/reps clock
    representation is half the clocking frequency, as triggering only occurs
    on a rising edge. Thus a given pulse sequence is not necessarily a valid
    clocking signal. By instead specifying a number of clock cycles (n_clocks)
    and the number of times which the signal should be switched over this number
    of cycles (toggles), an arbitrary digital pulse sequence is directly
    represented by this clocking signal itself, removing the need to send and
    store a separate digital data line.
    """

    ct_clock = []

    for i, tick in enumerate(clock):

        # the first (toggles)/(clocks) has a special meaning,
        # which specifies (the inital state)/(# clocks to hold it for)
        # NB. n_clocks=n => wait n-1 clock cycles before toggling
        if i == 0:
            if isinstance(output, DigitalOut):
                initial_state = output.raw_output[0]
            elif isinstance(output, AnalogOut):
                # for analog outputs, board expects zero as initial clock state
                initial_state = 0
            else:
                raise LabscriptError("Conversion to clocks and toggles not supported for output type '{}'.".format(output.__class__.__name__))

            n_clocks = int(tick['step'] * clock_limit) - 1
            ct_clock.append((n_clocks, initial_state))
            tick['reps'] -= 1  # have essentially dealt with 1 rep above

            # if no more reps then we are done with this instruction
            if tick['reps'] == 0:
                continue

        # period = int(round(tick['step'] / clock_resolution) * clock_resolution)

        # subtract 1 due to auto toggling
        # FIXME: ensure this is valid at every step, might just be required after first instruction?
        toggles = tick['reps'] - 1
        n_clocks = int(tick['step'] * clock_limit) - 1

        ct_clock.append((n_clocks, toggles))

    return ct_clock


def expand_clock(clock, clock_limit, stop_time):
    """ given a clocks/toggles clocking signal, return
        a list of times at which the clock ticks. """
    # FIXME: add clock resolution stuff
    times = []

    for i, tick in enumerate(clock):
        n_clocks, toggles = tick

        # first instruction is special, toggles gives initial state,
        # n_clocks gives number of clocks to hold it for
        if i == 0:
            times.append(n_clocks / clock_limit)
        else:
            for i in range(toggles):
                new_time = times[-1] + (n_clocks / clock_limit)
                # ensure we don't exceed the stop time
                if new_time > stop_time:
                    break
                else:
                    times.append(new_time)

    return times


def get_output_port_names(connection_table, device_name):
    """ Return list of connection names of the outputs attached, by inspecting the connection table. """

    output_names = []
    device_conn = connection_table.find_by_name(device_name)

    # iterate over the pseudoclock connections and find the type of output ultimately attached to it
    for pseudoclock_conn in device_conn.child_list.values():
        clockline_conn = pseudoclock_conn.child_list.values()[0]
        id_conn = clockline_conn.child_list.values()[0]
        output_conn = id_conn.child_list.values()[0]

        output_names.append(output_conn.parent_port)

    return output_names


class FPGAWait:

    # h5py doesn't support None... FIXME: reconsider this class
    null_value = np.nan

    def __init__(self, board_number=None, channel_number=None, value=None, comparison=None):
        self.board_number = board_number if board_number is not None else self.null_value
        self.channel_number = channel_number if channel_number is not None else self.null_value
        self.value = value if value is not None else self.null_value
        self.comparison = comparison if comparison is not None else self.null_value


@labscript_device
class FPGADevice(PseudoclockDevice):
    """ A device with indiviually pseudoclocked outputs. """

    clock_limit = 100e6  # 100 MHz
    clock_resolution = 1e-9  # true value?

    description = "FPGA-Device"
    allowed_children = [Pseudoclock]

    def __init__(self, name, n_analog=None, n_digital=None):
        """ n_analog: number of analog outputs expected (optional, unlimited if unspecified)
            n_digital: number of digital outputs expected (optional, unlimited if unspecified)
        """
        # device is triggered by PC, so trigger device is None and this device becomes the master_pseudoclock
        PseudoclockDevice.__init__(self, name)

        self.BLACS_connection = None  # FIXME: make this something useful?

        # number of outputs of each type that device should have, if specified
        self.n_analog = n_analog
        self.n_digital = n_digital

        self.pseudoclocks = []
        self.clocklines = []
        self.output_devices = []

        self.waits = []

    # restrict devices here?
    #def add_device(...):

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
            pc = Pseudoclock("fpga_pseudoclock{}".format(n), self, "clock_{}".format(n))
            self.pseudoclocks.append(pc)

            # Create the internal direct output clock_line
            cl = ClockLine("fpga_output{}_clock_line".format(n), pc, "fpga_internal{}".format(n))
            # FIXME: do we really need to store the list of clocklines?
            self.clocklines.append(cl)

            # Create the internal intermediate device (outputs) connected to the above clock line
            oid = OutputIntermediateDevice("fpga_output_device{}".format(n), cl)
            self.output_devices.append(oid)
            return oid

    def wait(self, at_time, board_number=None, channel_number=None, value=None, comparison=None):
        # ensure we have an entry in the labscript compiler wait table
        labscript.wait(label='wait{}'.format(len(self.waits)), t=at_time, timeout=5)
        self.waits.append(FPGAWait(board_number, channel_number, value, comparison))

    def generate_code(self, hdf5_file):
        # FIXME: restrict length of clock instructions/data based on hardware limitations

        # check that correct number of outputs are attached
        outputs = [output_device.output.__class__ for output_device in self.output_devices]

        n_analog = outputs.count(AnalogOut)
        n_digital = outputs.count(DigitalOut)

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

        PseudoclockDevice.generate_code(self, hdf5_file)

        # group in which to save instructions for this device
        device_group = hdf5_file.create_group("/devices/{}".format(self.name))

        # create subgroups for the clocks, analog data, and analog limits
        clock_group = device_group.create_group("clocks")
        analog_data_group = device_group.create_group("analog_data")
        analog_limits_group = device_group.create_group("analog_limits")
        waits_group = device_group.create_group("waits")

        # FIXME: inefficient/unclear to have to reprocess the data structure here
        for i, wait in enumerate(self.waits):
            wait = wait.__dict__
            dtype = [(wait.keys()[i], type(wait.values()[i])) for i in range(4)]
            wait = np.array(tuple(wait.values()), dtype=dtype)
            waits_group.create_dataset("wait{}".format(i), data=wait, compression=config.compression)


        for i, pseudoclock in enumerate(self.pseudoclocks):

            output = self.output_devices[i].output
            output_connection = output.connection

            if output is None:
                raise LabscriptError("OutputDevice '{}' has no Output connected!".format(output.name))

            # combine instructions with equal periods
            pseudoclock.clock = reduce_clock_instructions(pseudoclock.clock)  # , self.clock_resolution)

            # for digital outs, change from period/reps system to clocks/toggles (see function for explanation)
            if isinstance(output, DigitalOut):
                pseudoclock.clock = convert_to_clocks_and_toggles(pseudoclock.clock, output, self.clock_limit)  # , self.clock_resolution)
                clock_dtype = [('n_clocks', int), ('toggles', int)]
            else:
                # for other outputs (analog) we just use the period/reps form.

                # pack values into a data structure from which we can initialize an np array directly
                pseudoclock.clock = [tuple(tick.values()) for tick in pseudoclock.clock]
                clock_dtype = [('period', int), ('reps', int)]

            clock = np.array(pseudoclock.clock, dtype=clock_dtype)

            clock_group.create_dataset(output_connection,
                                       data=clock,
                                       compression=config.compression)

            # we only need to save analog data, digital outputs are
            # constructed from the clocks/toggles clocking signal
            if isinstance(output, AnalogOut):
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


class FPGAWaitMonitor:
    pass


class OutputIntermediateDevice(IntermediateDevice):
    """ An intermediate device that connects to some output device. """

    allowed_children = [AnalogOut, DigitalOut]

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
            # allow the connection name to be "analog #" or "digital #" only
            try:
                prefix, channel = device.connection.split(' ')
                if prefix != "analog" and prefix != "digital":
                    raise ValueError
                channel = int(channel)
            except ValueError:
                raise LabscriptError("{} {} has invalid connection string '{}'."
                                     "Format must be 'analog|digital #'.".format(device.description, device.name, str(device.connection)))
            IntermediateDevice.add_device(self, device)
            self.output = device  # store reference to the output


#########
# BLACS #
#########


@BLACS_tab
class FPGADeviceTab(DeviceTab):

    def initialise_GUI(self):

        # FIXME: add these
        self.base_units = 'Hz'
        # self.base_min
        # self.base_max
        # self.base_step
        # self.base_decimals

        output_names = get_output_port_names(self.connection_table, self.device_name)
        digital_properties = {}
        analog_properties = {}

        # properties['base_unit'], properties['min'], properties['max'], properties['step'], properties['decimals']
        for name in output_names:
            # the name format assumed here is enforced by add_device method of our IntermediateDevice
            output_type, num = name.split()
            if output_type == "analog":
                analog_properties[name] = {'base_unit': self.base_units,
                                           'min': 0.0, 'max': 10.0, 'step': 0.1, 'decimals': 3}
            elif output_type == "digital":
                digital_properties[name] = {}

        self.create_analog_outputs(analog_properties)
        self.create_digital_outputs(digital_properties)
        DDS_widgets, AO_widgets, DO_widgets = self.auto_create_widgets()

        self.style_widgets(AO_widgets, DO_widgets)
        self.auto_place_widgets(AO_widgets, DO_widgets)

        self.supports_smart_programming(True)

    def style_widgets(self, AO_widgets, DO_widgets):
        """ Apply stylesheets to widgets. """
        for output_name in DO_widgets:
            DO_widgets[output_name].setStyleSheet(fpga_widgets_style.DO_style)

    def get_output_port_names(self):
        """ Return list of connection names of the outputs attached, by inspecting the connection table. """

        output_names = []
        device_conn = self.connection_table.find_by_name(self.device_name)

        # iterate over the pseudoclock connections and find the type of output ultimately attached to it
        for pseudoclock_conn in device_conn.child_list.values():
            clockline_conn = pseudoclock_conn.child_list.values()[0]
            id_conn = clockline_conn.child_list.values()[0]
            output_conn = id_conn.child_list.values()[0]

            output_names.append(output_conn.parent_port)

        return output_names

    def initialise_workers(self):
        initial_values = self.get_front_panel_values()
        # pass initial front panel values to worker for manual programming cache
        self.create_worker("main_worker", FPGADeviceWorker, {'initial_values': initial_values})
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
        # when the pulseblaster is waiting. This indicates the end of
        # an experimental run.
        self.status, waits_pending = yield(self.queue_work(self.primary_worker, 'check_status'))

        if notify_queue is not None and self.status['waiting'] and not waits_pending:
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
        self.start()
        # poll status every 100ms to notify Queue Manager at end of shot
        self.statemachine_timeout_add(100, self.status_monitor, notify_queue)


@BLACS_worker
class FPGADeviceWorker(Worker):

    def init(self):
        # do imports here otherwwise "they will be imported in both the parent and child
        # processes and won't be cleanly restarted when the subprocess is restarted."
        from labscript_devices.fpga_api import FPGAInterface

        self.interface = FPGAInterface(0x0403, 0x6001)

        # define these aliases so that the DeviceTab class can see them
        self.start = self.interface.start
        self.stop = self.interface.stop
        self.reset = self.interface.reset
        self.send_parameter = self.interface.send_parameter

        # cache for smart programming
        # initial_values attr is created by the DeviceTab initialise_workers method
        # and reflects the initial state of the front panel values for manual_program to inspect
        self.smart_cache = {'clocks': {}, 'data': {}, 'output_values': self.initial_values}

    def check_status(self):
        # FIXME: implement
        return {'waiting': True}, False

    def program_manual(self, values):
        """ Program device to output values when not executing a buffered shot, ie. realtime mode. """
        
        modified_values = {}

        for output_name in values:
            value = values[output_name]

            # only update output if it has changed
            if value != self.smart_cache['output_values'].get(output_name):
                output_type, channel_number = output_name.split()
                channel_number = int(channel_number)

                # the value sent to the board may be coerced/quantized from the one requested
                # send_realtime_value returns the actual value the board is now outputting
                # so we can update the front panel to accurately reflect this
                # FIXME: remove hardcoded board number and range values
                new_value = self.interface.send_realtime_value(0, channel_number, value, 0, 10, output_type)
                modified_values[output_name] = new_value
                self.smart_cache['output_values'][output_name] = new_value

        return modified_values

    def transition_to_buffered(self, device_name, h5file, initial_values, fresh_program):
        """  This function is called whenever the Queue Manager requests the
        device to move into buffered mode in preparation for executing a buffered sequence. """

        with h5py.File(h5file, 'r') as hdf5_file:
            device_group = hdf5_file["devices"][device_name]

            # FIXME: might be better to make local copies of these so h5 file
            # can be closed sooner (in theory could speed up experiment cycle)
            clocks = device_group['clocks']
            analog_data = device_group['analog_data']
            limits = device_group['analog_limits']
            waits = device_group['waits']

            # value of each output at end of shot
            final_state = {}

            # send the pseudoclocks
            for i, output in enumerate(clocks):
                clock = clocks[output].value
                # only send if it has changed or fresh program is requested
                if fresh_program or np.any(clock != self.smart_cache['clocks'].get(output)):
                    self.smart_cache['clocks'][output] = clock
                    # FIXME: remove hardcoded board_number
                    self.interface.send_pseudoclock(board_number=0, channel_number=i, clock=clock)

                # if there is no entry for this output in the analog data group, it must be a digital out
                if not analog_data.get(output):
                    # then determine what the final state of the digital out is (initial state + n_toggles mod 2)
                    # FIXME: check this is right - might be off by 1!
                    n_toggles = sum(clock['toggles'])
                    final_state[output] = clock[0]['toggles'] + (n_toggles % 2)

            # send the analog data
            for i, output in enumerate(analog_data):
                data = analog_data[output].value
                # only send if it has changed or fresh program is requested
                if fresh_program or np.any(data != self.smart_cache['data'].get(output)):
                    final_state[output] = data[-1]
                    self.smart_cache['data'][output] = data
                    try:
                        range_min, range_max = limits[output].value
                    except KeyError:
                        # FIXME: what should the default range be?
                        range_min, range_max = 0, 5
                    # FIXME: remove hardcoded board_number
                    self.interface.send_analog_data(board_number=0, channel_number=i,
                                                    range_min=range_min, range_max=range_max, data=data)
            
            # send the waits
            for i, wait in enumerate(waits):
                wait = waits[wait].value
                self.interface.send_wait(wait['board_number'], wait['channel_number'], wait['value'], wait['comparison'])

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


#@BLACS_worker
#class AcquisitionWorker(Worker):
    #"""Check input values in real time."""
    #pass


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
        self.output_port_names = get_output_port_names(connection_table, self.device_name)

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


