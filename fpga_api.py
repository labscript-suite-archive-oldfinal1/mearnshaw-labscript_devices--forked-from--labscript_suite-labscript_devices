""" API to communicate with FPGA over USB using defined protocol
    Requires libftdi.
"""

import struct
import logging
logging.basicConfig(level=logging.DEBUG)

try:
    import ftdi
except ImportError:
    import ftdi1 as ftdi


def int_to_bytes(i, length=None):
    """ Convert int to byte buffer, optionally padding to a specified length. """
    bytes_ = []
    while i > 0:
        n = i % 256
        bytes_.insert(0, n)
        i >>= 8

    if length is not None:
        # add some padding null bytes at start
        diff = length - len(bytes_)
        bytes_[:0] = [0] * diff

    return ''.join(struct.pack('B', x) for x in bytes_)

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
ftdi.ftdi_usb_open = error_check(ftdi.ftdi_usb_open)
ftdi.ftdi_usb_close = error_check(ftdi.ftdi_usb_close)
ftdi.ftdi_set_bitmode = error_check(ftdi.ftdi_set_bitmode)


class FPGAInterface:

    realtime_mode_identifier = 0
    pseudoclock_mode_identifier = 1
    data_mode_identifier = 2
    parameter_mode_identifier = 3
    trigger_mode_identifier = 4

    def __init__(self, vendor_id=0x0403, product_id=0x6001):
        self.vendor_id = vendor_id
        self.product_id = product_id

        # create a new context
        self.ftdi_c = ftdi.ftdi_new()

        # open first device with the supplied VID:PID
        # FIXME: ok to assume 1 device or should we require more info (eg. serial) so we can choose ?
        ftdi.ftdi_usb_open(self.ftdi_c, self.vendor_id, self.product_id)

        # do EEPROM stuff

        # enter 245 synchronous FIFO mode with all bits set as outputs (0xFF)
        ftdi.ftdi_set_bitmode(self.ftdi_c, 0xFF, ftdi.BITMODE_SYNCFF)
        
    # FIXME: make this class a proper context manager instead?
    def close(self):
        # close device and free context
        ftdi.ftdi_usb_close(self.ftdi_c)
        ftdi.ftdi_free(self.ftdi_c)

    def __del__(self):
        # close device and free context when interface destroyed
        self.close()

    def send_bytes(self, bytes_):
        """ write a sequence of byte(s) to device. """
        logging.debug("writing {} bytes: {}".format(len(bytes_), repr(bytes_)))
        n_bytes_written = ftdi.ftdi_write_data(self.ftdi_c, bytes_, len(bytes_))

        if n_bytes_written < len(bytes_):
            raise FTDIError("Problem writing to device, check connection - device may be closed?")

        return n_bytes_written

    def send_value(self, value, n_bytes=None):
        """ Send value, optionally coercing to a fit specified number of bytes. """
        bytes_ = int_to_bytes(value, length=n_bytes)
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

    def send_analog_data(self, board_number, channel_number, data):
        """ Send analog data to a given channel on a given board. """
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
            # pack data/address into 2 bytes
            self.send_value(address, n_bytes=2)
            self.send_value(datum, n_bytes=2)
            address += 1  # FIXME: how to deal with/specify addresses?

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
