"""Various useful functions."""
import struct


def get_output_port_names(connection_table, device_name):
    """Return list of connection names of the outputs attached, by inspecting the connection table."""

    output_names = []
    device_conn = connection_table.find_by_name(device_name)

    # iterate over the pseudoclock connections and find the type of output ultimately attached to it
    for pseudoclock_conn in device_conn.child_list.values():
        clockline_conn = pseudoclock_conn.child_list.values()[0]
        id_conn = clockline_conn.child_list.values()[0]
        output_conn = id_conn.child_list.values()[0]
        output_names.append((output_conn.name, output_conn.parent_port))

    return output_names


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



