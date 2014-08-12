"""
    API to communicate with FPGA over USB using defined protocol
    Requires libftdi.
"""

import struct
import inspect
import logging

from labscript_devices.FPGADevice.fpga_wait import FPGAWait

logger = logging.getLogger('main')
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler('/home/matt/sequence.log')
file_handler.setLevel(logging.DEBUG)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

import ftdi1 as ftdi
import time

buffered = True


def value_to_bytes(i, length=None):
    """ Convert int to byte buffer, optionally padding or truncating to a specified length. """
    bytes_ = []
    while i > 0:
        n = i % 256
        bytes_.insert(0, n)
        i >>= 8

    if length is not None:
        diff = length - len(bytes_)

        if diff >= 0:
            # pad
            bytes_[:0] = [0] * diff
        else:
            # truncate
            bytes_ = bytes_[:length]

    return ''.join(struct.pack('B', x) for x in bytes_)


def quantize_analog_value(value, range_min, range_max):
    """ DAC output specified by 16 bits with 0x0000 set to the
    minimum of the range, 0xFFFF the maximum of the range (6 ranges
    are possible with our LTC1592 DACs).

    Returns value to be packed in the 16-bit data word to specify
    the desired output given the currently programmed range, and
    the quantized value it represents. """

    step = (range_max - range_min) / (2.0**16 - 1)
    # deal with extreme values first
    if value > range_max:
        return int(2.0**16 - 1), int(step * (2.0**16 - 1))
    elif value < range_min:
        return 0, 0
    else:
        try:
            DAC_data = int(round((value - range_min) / step))
        except ValueError:
            return 0, 0
        quantized = round(value / step) * step
        return quantized, DAC_data


class FTDIError(Exception):
    pass


def error_check(fn):
    """ decorator to check for and handle FTDI errors """
    def checked(*args):
        ret_val = fn(*args)  # libftdi python bindings don't accept kwargs
        # some functions return a tuple with the return code as its first value
        try:
            ft_status = ret_val[0]
            ret_val = ret_val[1]  # don't return the error code
        except TypeError:
            ft_status = ret_val
        # error values are negative (FIXME: or a null pointer, can we reliably test for that? None might be returned legitimately.)
        if ft_status < 0:
            try:
                err_msg = "An FTDI error occurred while calling '{}'".format(fn.__name__)
                # assume the context is the first argument (...not aware of a counterexample)
                context = args[0]
                ftdi_err_msg = ftdi.get_error_string(context)
                raise FTDIError("{}: {}".format(err_msg, ftdi_err_msg))
            except (IndexError, TypeError):
                raise FTDIError(err_msg)
        else:
            return ret_val
    return checked

# wrap ftdi functions in error checking/handling code
# our error checking code calls get_error_string so don't wrap it- could cause infinite recursion
# also don't wrap the functions returning void, no way to determine their success
exclude = ("get_error_string", "list_free", "list_free2", "set_usbdev", "deinit", "free", "set_ft232h_cbus")
ftdi_members = inspect.getmembers(ftdi, inspect.isfunction)
for member in ftdi_members:
    name, fn = member
    if name not in exclude:
        vars(ftdi)[name] = error_check(fn)


class FPGAModes:
    """Mode identifiers."""
    realtime = 0
    pseudoclock = 1
    data = 2
    parameter = 3
    trigger = 4
    repeat = 5
    pc_wait = 6
    digital_wait = 7
    analog_wait = 8
    wait_times = 9
    output_range = 10
    reset = 11


class FPGAStates:
    """State identifiers."""
    shot_finished = '\x07'


class FPGAInterface:
    # default VID:PID are for the FT232 chip
    def __init__(self, vendor_id=0x0403, product_id=0x6014):
        self.vendor_id = vendor_id
        self.product_id = product_id

        # create a new context
        self.c = ftdi.new()

        # open first device with the supplied VID:PID
        ftdi.usb_open(self.c, self.vendor_id, self.product_id)

        self.init_chip(bitmode=ftdi.BITMODE_SYNCFF)

        # more efficient to send as much data as possible in a single write,
        # see FTDI Technical Note TN_103 for more info, hence write_buffer
        self.write_buffer = []

    def init_chip(self, bitmode):
        # enter 245 synchronous FIFO mode with all bits set as outputs (0xFF)
        # assumes external EEPROM is set to 245 FIFO mode
        ftdi.set_latency_timer(self.c, 2)
        ftdi.set_bitmode(self.c, 0xFF, ftdi.BITMODE_RESET)
        ftdi.usb_purge_buffers(self.c)
        ftdi.set_bitmode(self.c, 0xFF, bitmode)
        ftdi.write_data_set_chunksize(self.c, 16)

    def close(self):
        # close device and free context
        ftdi.usb_close(self.c)
        ftdi.free(self.c)

    def __del__(self):
        # close device (and implicitly free context) when interface destroyed
        self.close()

    def send_bytes(self, bytes_, buffered=buffered):
        """ write a sequence of byte(s) to device.
            If buffered (default True) then value will be not be written until send_buffer is called. """

        if buffered:
            self.write_buffer.append(bytes_)
            #logging.debug("buffered {} bytes: {}".format(len(bytes_), repr(bytes_)))
        else:
            self.send_buffer()  # send any currently buffered data so order is maintained
            logger.debug("writing {} bytes: {}".format(len(bytes_), repr(bytes_)))
            n_bytes_written = ftdi.write_data(self.c, bytes_, len(bytes_))

            if n_bytes_written < len(bytes_):
                raise FTDIError("Problem writing to device, check connection - device may be closed?")

            return n_bytes_written

    def receive_bytes(self, n_bytes):
        try:
            return ftdi.read_data(self.c, n_bytes)
        except TypeError:
            # don't think there's any way out of this...
            raise NotImplementedError("read_data is broken in this version of libftdi, please upgrade.")

    def check_status(self):
        """ Read a byte from device and interpret it as a status code."""
        status = self.receive_bytes(n_bytes=100)
        if status == FPGAStates.shot_finished:
            return "Finished (Code: {}).".format(status)
        else:
            return "Not finished (Code: {}).".format(status)

    def send_buffer(self):
        """ send whatever is in the write_buffer to the device. """
        if self.write_buffer:
            byte_sequence = ''.join(self.write_buffer)
            self.write_buffer = []  # clear the buffer
            return self.send_bytes(byte_sequence, buffered=False)

    def send_value(self, value, n_bytes=None, buffered=buffered):
        """ Send value, optionally coercing to a fit specified number of bytes.
            If buffered (default True) then value will be not be written until send_buffer is called. """
        bytes_ = value_to_bytes(value, length=n_bytes)
        if buffered:
            self.write_buffer.append(bytes_)
            #logging.debug("buffered {} bytes: {} ({})".format(len(bytes_), repr(bytes_), value))
        else:
            self.send_buffer()  # send any currently buffered data so order is maintained
            return self.send_bytes(bytes_, buffered=False)

    def send_pseudoclock(self, board_number, channel_number, clock):
        """ Send pseudoclock to a given channel on a given board. """
        # send identifier (1 byte)
        self.send_value(FPGAModes.pseudoclock, n_bytes=1)
        # send board number (1 byte)
        self.send_value(board_number, n_bytes=1)
        # send channel number (1 byte)
        self.send_value(channel_number, n_bytes=1)

        # 10us delay
        time.sleep(10/1000000.0)

        n_words = len(clock)  # takes 1 word (4 bytes) to send #clocks, and 1 to send toggles
        # send number of words (1 byte)
        self.send_value(n_words, n_bytes=1)

        # send clocks/toggles (reps/period for analog), each is packed into a 4 byte word
        for tick in clock:
            self.send_value(tick[1], n_bytes=4)
            self.send_value(tick[0], n_bytes=4)

        # submit bufferred values
        #self.send_buffer()

    # FIXME: clarify this logic!
    def send_wait_info(self, board_number, channel_number, value, comparison):

        # analog waits have comparison
        if comparison != FPGAWait.null_value:
            self.send_value(FPGAModes.analog_wait, n_bytes=1)
            self.send_value(board_number, n_bytes=1)
            self.send_value(channel_number, n_bytes=1)
            # FIXME: remove hardcoded ranges
            quantized_value, DAC_value = quantize_analog_value(value, range_min=0, range_max=5)
            self.send_value(DAC_value, n_bytes=2)
            self.send_value(comparison, n_bytes=1)
        else:
            # we have digital or pc wait
            try:
                self.send_value(board_number, n_bytes=1)
            except TypeError:
                # board/channel no. is nan, so we have a "PC Wait"
                self.send_value(FPGAModes.pc_wait, n_bytes=1)

            self.send_value(channel_number, n_bytes=1)
            self.send_value(value, n_bytes=1)
 
        #self.send_buffer()

    def send_wait_times(self, times):
        self.send_value(FPGAModes.wait_times, n_bytes=1)
        for time in times:
            self.send_value(int(time), n_bytes=8)
        #self.send_buffer()

    def send_analog_data(self, board_number, channel_number, range_min, range_max, data):
        """ Send analog data to a given channel on a given board.

            range_min, range_max are the min/max output voltages configured on the DAC on this channel
        """
        # send identifier
        self.send_value(FPGAModes.data, n_bytes=1)
        # send board number
        self.send_value(board_number, n_bytes=1)
        # send channel number
        self.send_value(channel_number, n_bytes=1)
        n_words = len(data)  # address and data transmitted in a single word
        # send number of words (NB. two bytes)
        self.send_value(n_words, n_bytes=2)

        # send addressed data
        address = 0  # FIXME: how to deal with/specify addresses?
        for datum in data:
            # pack address into 2 bytes
            self.send_value(address, n_bytes=2)

            # pack quantized value into 2 bytes
            quantized_value, DAC_data = quantize_analog_value(datum, range_min, range_max)
            self.send_value(DAC_data, n_bytes=2)
            address += 1  # FIXME: how to deal with/specify addresses?

        #self.send_buffer()

    def send_realtime_value(self, board_number, channel_number, value, range_min, range_max, output_type):
        """ Send value to an output in real-time.
            output_type is either 'analog' or 'digital'.

            Returns the (possibly coerced/quantized) value sent to the board. """

        # send mode identifier
        self.send_value(FPGAModes.realtime, n_bytes=1)
        # send board number
        self.send_value(board_number, n_bytes=1)
        # send channel number
        self.send_value(channel_number, n_bytes=1)

        if output_type == "analog":
            value, DAC_data = quantize_analog_value(value, range_min, range_max)
            self.send_value(DAC_data, n_bytes=2)
        elif output_type == "digital":
            # value is bool for digital outs but since bool is a subclass of int, send_value works.
            self.send_value(value, n_bytes=1)
        # error or log warning if unknown output_type?

        #self.send_buffer()
        # return the value sent to the board
        return value

    def send_parameter(self, board_number, channel_number, value):
        """Update a parameter on an output."""
        # FIXME: need more info about the possible parameters etc.
        # send mode identifier
        self.send_value(FPGAModes.parameter, n_bytes=1)
        # send board number
        self.send_value(board_number, n_bytes=1)
        # send channel number
        self.send_value(channel_number, n_bytes=1)
        # send the parameter
        self.send_value(value, n_bytes=1)
        #self.send_buffer()

    def send_repeats_and_period(self, shot_reps, shot_period):
        # send mode identifier
        self.send_value(FPGAModes.repeat, n_bytes=1)
        # send shot reps (2 bytes)
        self.send_value(shot_reps, n_bytes=2)
        # send shot period (8 bytes)
        self.send_value(shot_period, n_bytes=8)
        #self.send_buffer()

    def send_output_range(self, board_number, channel_number, output_range):
        """Update DAC output range."""
        logger.debug("i.send_output_range(board_number={}, channel_number={}, index={})".format(board_number, channel_number, output_range))
        self.send_value(FPGAModes.output_range, n_bytes=1)
        self.send_value(int(board_number), n_bytes=1)
        self.send_value(int(channel_number), n_bytes=1)
        self.send_value(int(output_range), n_bytes=1)
        self.send_buffer()

    def start(self):
        """Trigger a shot."""
        try:
            self.send_value(FPGAModes.trigger, n_bytes=1)
            self.send_buffer()
        except FTDIError as err:
            # supply some extra info
            raise FTDIError("Error occurred while trying to send trigger: {}".format(err.message))

    def stop(self):
        """Stop output of board."""
        pass

    def reset(self):
        """Reset board."""
        logging.info("Resetting chip.")
        ftdi.set_bitmode(self.c, 0xFF, ftdi.BITMODE_RESET)
        ftdi.usb_reset(self.c)
        ftdi.usb_purge_buffers(self.c)
        logging.info("Reset chip.")
