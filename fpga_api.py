""" API to communicate with FPGA over USB using defined protocol
    Requires libftdi.
"""

import struct 

try:
    import ftdi
except ImportError:
    import ftdi1 as ftdi


def encode_pseudoclock(clock):
    """ Convert labscript generated pseudoclock into byte encoding expected by FPGA. """

    pass


def encode_analog_data(data):
    """ Convert labscript generated pseudoclock into byte encoding expected by FPGA. """
    pass

# status code
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

    def send_byte(self, data):
        byte = struct.pack("B", data)

        n_bytes_written = ftdi.ftdi_write_data(self.ftdi_c, byte, 1)

        if n_bytes_written != 1:
            raise FTDIError("Problem writing to device, check connection.")

        return n_bytes_written

    def send_bytes(self, bytes):
        """ send a packed byte sequence """
        for byte in bytes:
            self.send_byte(bytes)

    def send_pseudoclock(self, board_number, channel_number, clock):
        """ Send pseudoclock to a given channel on a given board. """
        # send identifier
        self.send_byte(self.pseudoclock_mode_identifier)

        # send board number
        self.send_byte(board_number)

        # send channel number
        self.send_byte(channel_number)
        
        # takes 1 word to send #clocks, and 1 to send toggles
        n_words = 2 * len(clock)  
        # send number of words
        self.send_byte(n_words)

        # send clocks and toggles, each is packed into a 4 byte word
        for tick in clock:
            clocks = struct.pack(">I", tick['clocks'])
            self.send_bytes(clocks)
            toggles = struct.pack(">I", tick['toggles'])
            self.send_bytes(toggles)

    def send_analog_data(self, board_number, channel_number, data):
        """ Send analog data to a given channel on a given board. """
        # send identifier
        self.send_byte(self.data_mode_identifier)

        # send board number
        self.send_byte(board_number)

        # send channel number
        self.send_byte(channel_number)
        
        # address and data transmitted in a single word
        n_words = len(data)

        # send number of words
        self.send_byte(n_words)

        # send addressed data
        address = 0  # FIXME: how to deal with/specify addresses?
        for datum in data:
            # pack data/address into 2 bytes
            data = struct.pack(">I", datum)[-2:]
            address = struct.pack(">I", address)[-2:]
            self.send_bytes(address)
            self.send_byte(data)

    def start(self):
        """ Trigger a shot. """
        try:
            self.send_byte(self.trigger_mode_identifier)
        except FTDIError as err:
            # supply some extra info
            raise FTDIError("Error occurred while trying to send trigger: {}".format(err.message))

    def stop(self):
        """ Stop output of board. """
        pass
