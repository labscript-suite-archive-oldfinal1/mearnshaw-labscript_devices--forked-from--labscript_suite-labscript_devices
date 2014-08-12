class OutputConnectionName(str):
    """The BLACS DeviceTab only has access to the connection table
    and not to instances of the Devices themselves. This class allows
    useful metadata to be encoded in/decoded from the connection string."""

    def __new__(self, type_=None, board_num=None, channel_num=None, group_name=None):
        name = "{}_{}_{}_{}".format(type_, board_num, channel_num, group_name)
        return str.__new__(self, name)

    def __init__(self, type_=None, board_num=None, channel_num=None, group_name=None):
        self.type_ = type_
        self.board_num = board_num
        self.channel_num = channel_num
        self.group_name = group_name
        self.name = "{}_{}_{}_{}".format(type_, board_num, channel_num, group_name)

    def __repr__(self):
        return repr(self.name)

    def __str__(self):
        return self.name

    # static because we'll typically use these after the instance has been reduced to a plain str
    @staticmethod
    def decode(name):
        output_type, board_number, channel_number, group_name = name.split('_')
        return output_type, int(board_number), int(channel_number), group_name

    @staticmethod
    def output_type(name):
        return OutputConnectionName.decode(name)[0]

    @staticmethod
    def board_number(name):
        return OutputConnectionName.decode(name)[1]

    @staticmethod
    def channel_number(name):
        return OutputConnectionName.decode(name)[2]

    @staticmethod
    def group_name(name):
        return OutputConnectionName.decode(name)[3]
