""" API to communicate with FPGA over USB using defined protocol. """
from pylibftdi import BitBangDevice


def encode_pseudoclock(clock):
    """ Convert labscript generated pseudoclock into byte encoding expected by FPGA. """

    pass

def encode_analog_data(data):
    """ Convert labscript generated pseudoclock into byte encoding expected by FPGA. """
    pass


class DummyDevice:
    port = 0x00

class FPGAInterface:
    pseudoclock_mode_identifier = 1
    data_mode_identifier = 2

    def __init__(self, device_identifier):
        #self.device = BitBangDevice(device_identifier)
        #self.device.direction = 0xFF  # set all bits as output
        self.device = DummyDevice()

    def send_byte(self, byte):
        self.device.port = (self.device.port & 0x00) | byte
        print hex(self.device.port)

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

        # send clocks and toggles
        for tick in clock:
            self.send_byte(tick['toggles'])
            self.send_byte(tick['n_clocks'])

    def send_analog_data(self, board_number, channel_number, data):
        """ Send analog data to a given channel on a given board. """
        # data = encode_analog_data(data)
        pass

