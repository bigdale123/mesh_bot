import logging
import time
import os
import open_meteo
from pubsub import pub
import meshtastic
import meshtastic.tcp_interface

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
)
log = logging.getLogger("MeshBot")

HELP_TEXT = (
    "Weather Bot 🌤\n"
    "A bot that fetches the weather.\n\n"
    "Examples:\n"
    "  wxbot location London\n"
    "  wxbot location 35005\n"
    "  wxbot location Paris, FR\n"
    "Type 'wxbot help' or 'wxbot ?' to see this message again."
)

def handle_weather_command(command, packet, interface):
    reply = ""

    if len(command) == 0 or command[0] in ("help", "?"):
        return HELP_TEXT

    if command[0] in ("location", "area"):
        location_str = " ".join(command[1:])

        if location_str:
            # User provided a location string
            coords = open_meteo.geocode(location_str)
            if not coords:
                return f"Sorry, location \"{location_str}\" not found."
            lat, lon, display = coords
        else:
            # No location provided — try sender's GPS
            node_id = packet.get("from")
            pos = get_node_position(interface, node_id)
            if not pos:
                return "No location provided and your node has no GPS position on record."
            lat, lon = pos
            display = f"your location ({lat:.4f}, {lon:.4f})"
            log.info("Using node GPS position: %s", display)

        weather = open_meteo.fetch_weather(lat, lon, display)
        if not weather:
            return f"Sorry, could not fetch weather for {display} right now."
        return weather

    return HELP_TEXT

def get_node_position(interface, node_id: int) -> tuple[float, float] | None:
    # Look up the last known GPS position of a node. Returns (lat, lon) or None.

    nodes = interface.nodes
    if not nodes:
        return None

    # nodes is a dict keyed by hex node ID string e.g. "!a1b2c3d4"
    for node in nodes.values():
        if node.get("num") == node_id:
            pos = node.get("position")
            if pos and "latitude" in pos and "longitude" in pos:
                return (pos["latitude"], pos["longitude"])
    return None

def handle_ping(packet, interface):
    # Respond to a ping with pong and signal statistics.
    from_id = packet.get("from")
    rx_rssi   = packet.get("rxRssi",   None)
    rx_snr    = packet.get("rxSnr",    None)
    hop_limit = packet.get("hopLimit", None)
    hop_start = packet.get("hopStart", None)

    # Number of hops taken = hopStart - hopLimit
    if hop_start is not None and hop_limit is not None:
        hops = hop_start - hop_limit
        hops_str = f"Hops: {hops}"
    else:
        hops_str = "Hops: unknown"

    rssi_str = f"RSSI: {rx_rssi} dBm" if rx_rssi is not None else "RSSI: unknown"
    snr_str  = f"SNR: {rx_snr} dB"   if rx_snr  is not None else "SNR: unknown"

    return f"🏓 Pong!\n{rssi_str}\n{snr_str}\n{hops_str}"

def filter_dm(packet: dict, interface) -> bool:
    """Only respond to direct messages addressed to this node."""
    to_id = packet.get("toId", "")
    if to_id == "^all" or to_id == "":
        return False
    if packet.get("to") != interface.myInfo.my_node_num:
        return False
    return True


def filter_channel(packet: dict, interface, channel: int = 0) -> bool:
    """Only respond to messages on a specific channel."""
    if packet.get("channel", 0) != channel:
        return False
    if packet.get("toId", "") != "^all":
        return False
    return True

def on_receive(packet, interface):
    try:
        decoded_packet = packet.get("decoded", {})

        # Filter packet based on chosen filter
        if not ACTIVE_FILTER(packet, interface):
            return
        
        client_node_id = packet.get("from", "unknown")
        message_text = decoded_packet.get("text", "").strip().lower()

        log.info("DM Received! Content: \n    %s", message_text)

        reply = ""
        command = message_text.split(" ")[1:]
        log.info("Command: %s", str(command))

        if message_text.startswith("wxbot"):
            reply = handle_weather_command(command, packet, interface)
        elif message_text.startswith("ping"):
            reply = handle_ping(packet, interface)

        if reply:
            if ACTIVE_FILTER is filter_dm:
                interface.sendText(reply, destinationId=client_node_id, wantAck=True)
            else:
                channel_index = int(os.environ.get("MESH_CHANNEL", 0))
                interface.sendText(reply, channelIndex=channel_index, wantAck=False)

    except Exception as e:
        log.exception("Error handling packet: %s", e)

def on_connect(interface, topic=pub.AUTO_TOPIC):
    log.info("Connected. Listening for commands...")

FILTERS = {
    "dm": filter_dm,
    "channel": filter_channel
}
filter_name = os.environ.get("MESH_FILTER", "dm").lower()
ACTIVE_FILTER = FILTERS.get(filter_name, filter_dm)
log.info("Using filter %s.", filter_name)
if ACTIVE_FILTER is filter_channel:
    channel = int(os.environ.get("MESH_CHANNEL", 0))
    log.info("Channel ID: %d", channel)
    ACTIVE_FILTER = lambda packet, interface: filter_channel(packet, interface, channel=channel)
    

if __name__ == "__main__":
    # Designed for use with a TCP meshtastic node
    host = os.environ.get("MESH_HOST", "10.0.0.90")
    port = int(os.environ.get("MESH_PORT", 4403))

    log.info("Connecting to node @ %s:%d ...", host, port)

    # register subscriptions to topics
    pub.subscribe(on_receive, "meshtastic.receive")
    pub.subscribe(on_connect, "meshtastic.connection.established")

    node_interface = meshtastic.tcp_interface.TCPInterface(hostname=host, portNumber=port)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping...")
    finally:
            node_interface.close()
