import logging
import time
import open_meteo
from pubsub import pub
import meshtastic
import meshtastic.tcp_interface

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
)
log = logging.getLogger("MeshWX")

HELP_TEXT = (
    "Weather Bot 🌤\n"
    "A bot that fetches the weather.\n\n"
    "Examples:\n"
    "  wxbot location London\n"
    "  wxbot location 35005\n"
    "  wxbot location Paris, FR\n"
    "Type 'wxbot help' or 'wxbot ?' to see this message again."
)

def handle_weather_command(command):
    reply = ""

    if len(command) >= 1:
        if command[0] in ("help", "?"):
            reply = HELP_TEXT
        elif command[0] in ("location", "area"):
            location = " ".join(command[1:])
            coords = open_meteo.geocode(location)

            if not coords:
                reply = f"Sorry, location \"{location}\" not found.\nPlease try rewording the location."
            else:
                weather = open_meteo.fetch_weather(coords[0], coords[1], coords[2])

                if not weather:
                    reply = f"Sorry, could not fetch weather for {location} right now.\nPlease try again later."
                else:
                    reply = weather
        else:
            reply = HELP_TEXT
    else:
        reply = HELP_TEXT

    return reply


def on_receive(packet, interface):
    try:
        decoded_packet = packet.get("decoded", {})

        # Ignore if packet is not DM.
        if decoded_packet.get("portnum") != "TEXT_MESSAGE_APP":
            return
        to_id = packet.get("toId", "")
        if to_id == "^all" or to_id == "": # ignore channel broadcasts
            return

        # Make sure the DM is addressed to this node
        node_id = interface.myInfo.my_node_num
        if packet.get("to") != node_id:
            return
        
        client_node_id = packet.get("from", "unknown")
        message_text = decoded_packet.get("text", "").strip().lower()

        log.info("DM Received! Content: \n    %s", message_text)

        reply = ""
        command = message_text.split(" ")[1:]
        log.info("Command: %s", str(command))

        if message_text.startswith("wxbot"):
            reply = handle_weather_command(command)


           

        interface.sendText(reply, destinationId=client_node_id, wantAck=True)



    except Exception as e:
        log.exception("Error handling packet: %s", e)

def on_connect(interface, topic=pub.AUTO_TOPIC):
    log.info("Connected. Listening for commands...")

if __name__ == "__main__":
    # Designed for use with a TCP meshtastic node
    host = "10.0.0.90"
    port = 4403

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
