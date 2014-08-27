import numpy as np


class FPGAWait:
    # h5py doesn't support None... FIXME: reconsider this class
    null_value = np.nan

    def __init__(self, board_number=None, channel_number=None, value=None, comparison=None):
        self.board_number = board_number if board_number is not None else self.null_value
        self.channel_number = channel_number if channel_number is not None else self.null_value
        self.value = value if value is not None else self.null_value
        self.comparison = ord(comparison) if comparison is not None else self.null_value
