""" API to communicate with FPGA over USB using defined protocol
    Requires libftdi.
"""

import struct

try:
    import ftdi
except ImportError:
    import ftdi1 as ftdi


def int_to_bytes(i, length=None):
    """ Convert int to byte buffer, optionally padding to a specified length. """
    bytes = []
    while i > 0:
        n = i % 256
        bytes.insert(0, n)
        i >>= 8

    if length is not None:
        # add some padding null bytes at start
        diff = length - len(bytes)
        bytes[:0] = [0] * diff

    return ''.join(struct.pack('B', x) for x in bytes)

# FTDI status codes
FT_OK = 0


class FTDIError(Exception):
    pass


def error_check(fn):
    """ decorator to check for and handle FTDI errors """
    def checked(*args):
        ft_status = fn(*args)  # libftdi python bindings don't accept kwargs
        if ft_status != FT_OK:
            try:
                # assume the context is the first argument (...not aware of a counterexample)
                err_msg = "An FTDI error occurred while calling '{}'".format(fn.__name__)
                context = args[0]
                ftdi_err_msg = ftdi.ftdi_get_error_string(context)
                raise FTDIError("{}: {}".format(err_msg, ftdi_err_msg))
            except (IndexError, TypeError):
                raise FTDIError(err_msg)
    return checked


# wrap functions in error checking/handling code
ftdi.usb_open = error_check(ftdi.ftdi_usb_open)
ftdi.set_bitmode = error_check(ftdi.ftdi_set_bitmode)


class FPGAInterface:
    vendor_id = 0x0403
    product_id = 0x6001

    realtime_mode_identifier = 0
    pseudoclock_mode_identifier = 1
    data_mode_identifier = 2
    parameter_mode_identifier = 3
    trigger_mode_identifier = 4

    def __init__(self):  # device_identifier):
        # create a new context
        self.ftdi_c = ftdi.ftdi_new()
        ftdi.usb_open(self.ftdi_c, self.vendor_id, self.product_id)

        # do EEPROM stuff

        # enter 245 synchronous FIFO mode with all bits set as outputs (0xFF)
        ftdi.set_bitmode(self.ftdi_c, 0xFF, ftdi.BITMODE_SYNCFF)

    def send_bytes(self, bytes_):
        n_bytes_written = ftdi.ftdi_write_data(self.ftdi_c, bytes_, len(bytes_))

        if n_bytes_written < len(bytes_):
            raise FTDIError("Problem writing to device, check connection.")

        return n_bytes_written

    def send_value(self, value, length=None):
        """ Send value, optionally coercing to a fit specified number of bytes. """
        bytes_ = int_to_bytes(value, length)
        return self.send_bytes(bytes_)

    def send_pseudoclock(self, board_number, channel_number, clock):
        """ Send pseudoclock to a given channel on a given board. """
        # send identifier (1 byte)
        self.send_value(self.pseudoclock_mode_identifier, 1)

        # send board number (1 byte)
        self.send_value(board_number, 1)

        # send channel number (1 byte)
        self.send_value(channel_number, 1)

        # takes 1 word to send #clocks, and 1 to send toggles
        n_words = 2 * len(clock)
        # send number of words (1 byte)
        self.send_value(n_words, 1)

        # send clocks and toggles, each is packed into a 4 byte word
        for tick in clock:
            self.send_value(tick['n_clocks'], 4)
            self.send_value(tick['toggles'], 4)

    def send_analog_data(self, board_number, channel_number, data):
        """ Send analog data to a given channel on a given board. """
        # send identifier
        self.send_value(self.data_mode_identifier, 1)

        # send board number
        self.send_value(board_number, 1)

        # send channel number
        self.send_value(channel_number, 1)

        # address and data transmitted in a single word
        n_words = len(data)

        # send number of words
        self.send_value(n_words, 1)

        # send addressed data
        address = 0  # FIXME: how to deal with/specify addresses?
        for datum in data:
            # pack data/address into 2 bytes
            self.send_value(address, 2)
            self.send_value(datum, 2)
            address += 1  # FIXME: how to deal with/specify addresses?

    def start(self):
        """ Trigger a shot. """
        try:
            self.send_value(self.trigger_mode_identifier, 1)
        except FTDIError as err:
            # supply some extra info
            raise FTDIError("Error occurred while trying to send trigger: {}".format(err.message))

    def stop(self):
        """ Stop output of board. """
        pass
