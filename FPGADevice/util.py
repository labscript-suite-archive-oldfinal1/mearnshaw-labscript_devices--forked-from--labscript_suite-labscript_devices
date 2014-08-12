"""Various useful functions."""


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
