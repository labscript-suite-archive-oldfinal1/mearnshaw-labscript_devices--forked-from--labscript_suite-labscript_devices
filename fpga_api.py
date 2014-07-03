""" API to communicate with FPGA over USB using defined protocol
    Requires libftdi.
"""

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
                err_msg = "An FTDI error occurred while calling '{}' with the parameters '{}'".format(fn.__name__,
                                                                                                      [repr(arg) for arg in args])
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
    
    pseudoclock_mode_identifier = 1
    data_mode_identifier = 2

    def __init__(self):  # device_identifier):
        # create a new context
        self.ftdi_c = ftdi.ftdi_new()
        ftdi.usb_open(self.ftdi_c, self.vendor_id, self.product_id)

        # do EEPROM stuff

        # enter 245 synchronous FIFO mode with all bits set as outputs (0xFF)
        ftdi.set_bitmode(self.ftdi_c, 0xFF, ftdi.BITMODE_SYNCFF)

    def send_data(self, data):
        try:
            n_bytes = len(data)
        except TypeError:
            data = str(data)
            n_bytes = len(data)

        ftdi.ftdi_write_data(self.ftdi_c, data, n_bytes)
        # check return value

    def send_pseudoclock(self, board_number, channel_number, clock):
        """ Send pseudoclock to a given channel on a given board. """
        # send identifier
        self.send_data(self.pseudoclock_mode_identifier)

        # send board number
        self.send_data(board_number)

        # send channel number
        self.send_data(channel_number)
        
        # takes 1 word to send #clocks, and 1 to send toggles
        n_words = 2 * len(clock)  
        # send number of words
        self.send_data(n_words)

        # send clocks and toggles
        for tick in clock:
            self.send_data(tick['toggles'])
            self.send_data(tick['n_clocks'])

    def send_analog_data(self, board_number, channel_number, data):
        """ Send analog data to a given channel on a given board. """
        # data = encode_analog_data(data)
        pass

