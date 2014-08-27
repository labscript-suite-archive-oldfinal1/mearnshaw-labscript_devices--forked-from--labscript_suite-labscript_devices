from labscript import AnalogOut, DigitalOut
from output_connection_name import OutputConnectionName


class FPGAAnalogOut(AnalogOut):
    def __init__(self, name, parent_device, board_number, channel_number, group_name=None, *args, **kwargs):
        connection = OutputConnectionName("analog", board_number, channel_number, group_name)
        AnalogOut.__init__(self, name, parent_device, connection, *args, **kwargs)


class FPGADigitalOut(DigitalOut):
    def __init__(self, name, parent_device, board_number, channel_number, group_name=None, *args, **kwargs):
        connection = OutputConnectionName("digital", board_number, channel_number, group_name)
        DigitalOut.__init__(self, name, parent_device, connection, *args, **kwargs)
