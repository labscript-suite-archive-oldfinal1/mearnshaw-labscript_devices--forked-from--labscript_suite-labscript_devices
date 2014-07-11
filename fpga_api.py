"""
    API to communicate with FPGA over USB using defined protocol
    Requires libftdi.
"""

import struct
import inspect
import logging

logging.basicConfig(level=logging.DEBUG)

try:
    import ftdi1 as ftdi
except ImportError:
    import ftdi
    # in this version of the library method names prefixed with ftdi_
    # rename them to exclude this prefix
    ftdi_members = inspect.getmembers(ftdi)
    for member in ftdi_members:
        name, fn = member
        new_name = name.replace("ftdi_", "")
        if new_name != name:
            vars(ftdi)[new_name] = fn
            del vars(ftdi)[name]


def value_to_bytes(i, length=None):
    """ Convert int to byte buffer, optionally padding to a specified length. """
    bytes_ = []
    while i > 0:
        n = i % 256
        bytes_.insert(0, n)
        i >>= 8

    if length is not None:
        diff = length - len(bytes_)
        bytes_[:0] = [0] * diff

    return ''.join(struct.pack('B', x) for x in bytes_)


def quantize_analog_value(value, range_min, range_max):
    """ DAC output specified by 16 bits with 0x0000 set to the
    minimum of the range, 0xFFFF the maximum of the range (6 ranges
    are possible with our LTC1592 DACs).

    Returns value to be packed in the 16-bit data word to specify
    the desired output given the currently programmed range, and
    the quantized value it represents. """
    step = (range_max - range_min) / (2.0**16 - 1)
    DAC_data = int(round((value - range_min) / step))
    quantized = DAC_data * step
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
        except TypeError:
            ft_status = ret_val

        # error values are negative or NULL pointer (None)
        if (ft_status < 0): # or (ft_status is None)
            try:
                # assume the context is the first argument (...not aware of a counterexample)
                err_msg = "An FTDI error occurred while calling '{}'".format(fn.__name__)
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


class FPGAInterface:

    realtime_mode_identifier = 0
    pseudoclock_mode_identifier = 1
    data_mode_identifier = 2
    parameter_mode_identifier = 3
    trigger_mode_identifier = 4

    # FIXME: change to the correct VID:PID for FT232H
    def __init__(self, vendor_id=0x0403, product_id=0x6014):  # product_id=0x6001):
        self.vendor_id = vendor_id
        self.product_id = product_id

        # create a new context
        self.c = ftdi.new()

        # open first device with the supplied VID:PID
        ftdi.usb_open(self.c, self.vendor_id, self.product_id)

        self.init_chip(bitmode=ftdi.BITMODE_SYNCFF)

    def init_chip(self, bitmode):
        # enter 245 synchronous FIFO mode with all bits set as outputs (0xFF)
        # assumes external EEPROM is set to 245 FIFO mode
        ftdi.set_latency_timer(self.c, 2)
        ftdi.set_bitmode(self.c, 0xFF, ftdi.BITMODE_RESET)
        ftdi.usb_purge_buffers(self.c)
        ftdi.set_bitmode(self.c, 0xFF, bitmode)

    # FIXME: make this class a proper context manager instead?
    def close(self):
        # close device and free context
        ftdi.usb_close(self.c)
        ftdi.free(self.c)

    """
    def __del__(self):
        # close device and free context when interface destroyed
        self.close()
    """

    def send_bytes(self, bytes_):
        """ write a sequence of byte(s) to device. """
        logging.debug("writing {} bytes: {}".format(len(bytes_), repr(bytes_)))
        n_bytes_written = ftdi.write_data(self.c, bytes_, len(bytes_))
        #n_bytes_written = ftdi.transfer_data_done(ftdi.write_data_submit(self.c, bytes_, len(bytes_)))

        if n_bytes_written < len(bytes_):
            raise FTDIError("Problem writing to device, check connection - device may be closed?")

        return n_bytes_written

    def send_value(self, value, n_bytes=None):
        """ Send value, optionally coercing to a fit specified number of bytes. """
        bytes_ = value_to_bytes(value, length=n_bytes)
        return self.send_bytes(bytes_)

    def send_pseudoclock(self, board_number, channel_number, clock):
        """ Send pseudoclock to a given channel on a given board. """
        # send identifier (1 byte)
        self.send_value(self.pseudoclock_mode_identifier, n_bytes=1)

        # send board number (1 byte)
        self.send_value(board_number, n_bytes=1)

        # send channel number (1 byte)
        self.send_value(channel_number, n_bytes=1)

        # takes 1 word (4 bytes) to send #clocks, and 1 to send toggles
        n_words = 2 * len(clock)
        # send number of words (1 byte)
        self.send_value(n_words, n_bytes=1)

        # send clocks and toggles, each is packed into a 4 byte word
        for tick in clock:
            self.send_value(tick['n_clocks'], n_bytes=4)
            self.send_value(tick['toggles'], n_bytes=4)

    def send_analog_data(self, board_number, channel_number, range_min, range_max, data):
        """ Send analog data to a given channel on a given board.

            range_min, range_max are the min/max output voltages configured on the DAC on this channel
        """
        # send identifier
        self.send_value(self.data_mode_identifier, n_bytes=1)

        # send board number
        self.send_value(board_number, n_bytes=1)

        # send channel number
        self.send_value(channel_number, n_bytes=1)

        # address and data transmitted in a single word
        n_words = len(data)

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

    def send_realtime_value(self, board_number, channel_number, value, range_min, range_max, output_type):
        """ Send value to an output in real-time.
            output_type is either 'analog' or 'digital'.

            Returns the (possibly coerced/quantized) value sent to the board. """

        # send mode identifier
        self.send_value(self.realtime_mode_identifier, n_bytes=1)

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

        # return the value sent to the board
        return value

    def send_parameter(self, board_number, channel_number, value):
        """ Update a parameter on an output. """
        # FIXME: need more info about the possible parameters etc.

        # send mode identifier
        self.send_value(self.parameter_mode_identifier, n_bytes=1)

        # send board number
        self.send_value(board_number, n_bytes=1)

        # send channel number
        self.send_value(channel_number, n_bytes=1)

        # send the parameter
        self.send_value(value, n_bytes=1)

    def start(self):
        """ Trigger a shot. """
        try:
            self.send_value(self.trigger_mode_identifier, n_bytes=1)
        except FTDIError as err:
            # supply some extra info
            raise FTDIError("Error occurred while trying to send trigger: {}".format(err.message))

    def stop(self):
        """ Stop output of board. """
        pass

    def reset(self):
        """ Reset board. """
        logging.info("Resetting chip.")
        ftdi.set_bitmode(self.c, 0xFF, ftdi.BITMODE_RESET)
        ftdi.usb_reset(self.c)
        ftdi.usb_purge_buffers(self.c)
        logging.info("Reset chip.")
