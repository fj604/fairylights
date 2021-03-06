import gc
import micropython
import machine
import neopixel
import uos
import utime
import ujson
import ubinascii
import network
import sys
import esp

from umqtt.robust import MQTTClient

import mqttcreds

PIN = const(2)
PIXELS = const(50)

WD_TIMEOUT_MS = 10000
COLOUR_MIN = const(0)
COLOUR_MAX = const(64)
BOOST_MULTIPLIER = const(4)
BOOST_MULTIPLIER_MAX = 4
DENSITY = const(16)
DENSITY_MAX = const(128)
DENSITY_MIN = const(1)
DENSITY_STEP_MULTIPLIER = const(2)
FADE_MULTIPLIER = const(15)
FADE_DIVIDER = const(16)
MQ_PING_INTERVAL_MS = const(15000)
DELAY_MS = const(10)
DELAY_STEP_MS = const(5)
DELAY_MAX_MS = const(50)
WEIGHT_RED = const(5)
WEIGHT_GREEN = const(3)
WEIGHT_BLUE = const(3)
STATE_FILENAME = "state.json"
CLIENT_ID = b"LEDcontroller_" + ubinascii.hexlify(machine.unique_id())
RETRY_DELAY_MS = const(500)

COLOURS = {
    "black":   (0, 0, 0),
    "red":     (0, 1, 0),
    "green":   (1, 0, 0),
    "blue":    (0, 0, 1),
    "yellow":  (1, 1, 0),
    "cyan":    (1, 0, 1),
    "magenta": (0, 1, 1),
    "white":   (1, 1, 1)
}

BLACK_PIXEL = (0, 0, 0)
RED_PIXEL = (0, 128, 0)
YELLOW_PIXEL = (128, 128, 0)
GREEN_PIXEL = (128, 0, 0)
DEFAULT_SOLID = (64, 64, 64)


def colour_max(colour, max_c):
    ret_colour = []
    if colour in COLOURS:
        found_c = COLOURS[colour]
        ret_colour = [i * max_c for i in found_c]
        return tuple(ret_colour)
    else:
        return False


def set_defaults():
    global lights_on, weight_red, weight_green, weight_blue
    global monochrome, animation, solid, red, green, blue
    global delay_ms, boost_multiplier, density
    global fade_multiplier, fade_divider
    weight_red = WEIGHT_RED
    weight_green = WEIGHT_GREEN
    weight_blue = WEIGHT_BLUE
    red = COLOUR_MAX
    green = COLOUR_MAX
    blue = COLOUR_MAX
    boost_multiplier = BOOST_MULTIPLIER
    fade_multiplier = FADE_MULTIPLIER
    fade_divider = FADE_DIVIDER
    density = DENSITY
    delay_ms = DELAY_MS
    solid = DEFAULT_SOLID
    animation = True
    lights_on = True
    monochrome = False


def save_state():
    state = {}
    state["lights_on"] = lights_on
    state["monochrome"] = monochrome
    state["solid"] = solid
    state["animation"] = animation
    state["red"] = red
    state["green"] = green
    state["blue"] = blue
    state["weight_red"] = weight_red
    state["weight_green"] = weight_green
    state["weight_blue"] = weight_blue
    state["delay_ms"] = delay_ms
    state["fade_multiplier"] = fade_multiplier
    state["fade_divider"] = fade_divider
    state["boost_multiplier"] = boost_multiplier
    state["density"] = density
    try:
        state_file = open(STATE_FILENAME, "w")
        state_file.write(ujson.dumps(state))
        state_file.close()
    except OSError as exception:
        print("Error saving state:", exception)
        return False
    return True


def set_state(state):
    for key, value in state.items():
        # The next line is lazy and unsafe - replace with proper input checks
        globals()[key] = value


def load_state():
    try:
        state_file = open(STATE_FILENAME, "r")
        state_string = state_file.read()
        state_file.close()
    except Exception as e:
        print("Error reading state:", e)
        return False
    try:
        new_state = ujson.loads(state_string)
    except ValueError:
        print("State not valid")
        return False
    set_state(new_state)
    return True


def message_callback(topic, msg):
    global lights_on, weight_red, weight_green, weight_blue, monochrome
    global animation, red, green, blue, delay_ms, boost_multiplier, density
    global solid
    print("Msg:", msg)
    msg = msg.lower()
    if msg == b"on":
        lights_on = True
    elif msg == b"off":
        lights_on = False
    elif msg in(b"colour", b"color"):
        monochrome = False
    elif msg == b"normal":
        set_defaults()
    elif msg == b"slower":
        if delay_ms + DELAY_STEP_MS < DELAY_MAX_MS:
            delay_ms += DELAY_STEP_MS
        else:
            delay_ms = DELAY_MAX_MS
    elif msg == b"faster":
        if delay_ms > DELAY_STEP_MS:
            delay_ms -= DELAY_STEP_MS
        else:
            delay_ms = 0
    elif msg == b"slow":
        delay_ms = DELAY_MAX_MS
    elif msg == b"fast":
        delay_ms = 0
    elif msg == b"dimmer":
        if boost_multiplier > 1:
            boost_multiplier -= 1
    elif msg == b"brighter":
        if boost_multiplier < BOOST_MULTIPLIER_MAX:
            boost_multiplier += 1
    elif msg == b"brightest":
        boost_multiplier = BOOST_MULTIPLIER_MAX
    elif msg == b"sparser":
        if density > DENSITY_MIN:
            density /= DENSITY_STEP_MULTIPLIER
    elif msg == b"denser":
        if density < DENSITY_MAX:
            density *= DENSITY_STEP_MULTIPLIER
    elif msg == b"sparse":
        density = DENSITY_MIN
    elif msg == b"dense":
        density = DENSITY_MAX
    elif msg == b"save":
        save_state()
    elif msg == b"restore":
        load_state()
    elif msg == b"solid":
        animation = False
    elif msg in (b"sparkle", b"sparkling"):
        animation = True
    elif msg.decode() in COLOURS:
        print("Setting colour to", msg)
        monochrome = COLOURS[msg.decode()]
    elif msg.decode()[0] == "#" and len(msg) == 7:
        animation = False
        colour_b = ubinascii.unhexlify(msg.decode()[1:])
        solid = (colour_b[1], colour_b[0], colour_b[2])
    else:
        try:
            new_state = ujson.loads(msg.decode())
        except ValueError:
            print("Unknown command")
            return
        print(new_state)
        set_state(new_state)


@micropython.native
def randmax(max_value):
    return uos.urandom(1)[0] % max_value if max_value else 0


def new_pixel_monochrome():
    m = randmax(COLOUR_MAX)
    c = []
    for i in monochrome:
        c.append(i * m * boost_multiplier)
    return tuple(c)


@micropython.native
def new_pixel_random():
    r = randmax(red)
    g = randmax(green)
    b = randmax(blue)
    total_weight = weight_red + weight_green + weight_blue
    if randmax(total_weight) < weight_red:
        r *= boost_multiplier
    if randmax(total_weight) < weight_green:
        g *= boost_multiplier
    if randmax(total_weight) < weight_blue:
        b *= boost_multiplier
    return(g, r, b)


@micropython.native
def animate(np):
    rnd = uos.urandom(PIXELS)
    np.buf = bytearray([v * fade_multiplier // fade_divider
                        if v > 1 else 0 for v in np.buf])
    for i in np_range:
        if rnd[i] < density and np[i] == BLACK_PIXEL:
            np[i] = (new_pixel_monochrome() if monochrome
                     else new_pixel_random())


def wdt(timer):
    global wd_fed, op
    if not wd_fed:
        print("Software WDT reset")
        print("Stuck op:", op)
        print("Mem alloc:", gc.mem_alloc())
        print("Mem free:", gc.mem_free()) 
        utime.sleep_ms(500)
        machine.reset()
    wd_fed = False


print("Initialising")
micropython.alloc_emergency_exception_buf(100)
machine.freq(160000000)
esp.sleep_type(esp.SLEEP_NONE)


ap = network.WLAN(network.AP_IF)
ap.active(True)

mq = MQTTClient(CLIENT_ID, mqttcreds.host, user=mqttcreds.user,
                password=mqttcreds.password)
np = neopixel.NeoPixel(machine.Pin(PIN), PIXELS)
np_range = range(0, PIXELS)

np.fill(BLACK_PIXEL)

set_defaults()
load_state()
lights_on = True

mq.set_callback(message_callback)

print("Waiting for WiFi")
np[0] = RED_PIXEL
np.write()
sta = network.WLAN(network.STA_IF)
while not sta.isconnected():
    utime.sleep_ms(RETRY_DELAY_MS)

print("Connecting to MQ")
np[1] = YELLOW_PIXEL
np.write()
mq_connected = False
while not mq_connected:
    try:
        mq.connect()
        mq_connected = True
    except Exception as exception:
        print("Can't connect to MQ:", exception)
        utime.sleep_ms(RETRY_DELAY_MS)

print("Subscribing to MQ")
np[2] = GREEN_PIXEL
np.write()
mq_subscribed = False
while not mq_subscribed:
    try:
        mq.subscribe(mqttcreds.topic)
        mq_subscribed = True
    except Exception as exception:
        print("Can't subscribe to MQ topic:", exception)
        utime.sleep_ms(RETRY_DELAY_MS)

print("Deactivating Access Point interface")
ap.active(False)

sta = network.WLAN(network.STA_IF)

print("Setting watchdog timer")
op = "init"
wd_fed = True
wd = machine.Timer(-1)
wd.init(period=WD_TIMEOUT_MS, mode=wd.PERIODIC, callback=wdt)

#print("Disabling auto GC")
#gc.disable()

gc.threshold(10240)

print("Starting main loop")

uptime = 0
while True:
    try:
        op = "mq_ping"
        if sta.isconnected():
            mq.ping()
        else:
            print("Not connected - can't ping MQ")
        deadline = utime.ticks_add(utime.ticks_ms(), MQ_PING_INTERVAL_MS)
        frames = 0
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            op = "mq_check"
            if sta.isconnected():
                mq.check_msg()
            else:
                print("Not connected - can't check MQ")
            wd_fed = True
            op = "animation"
            if lights_on:
                if animation:
                    animate(np)
                else:
                    np.fill(solid)
            else:
                np.fill(BLACK_PIXEL)
            op = "write"
            np.write()
            op = "sleep"
            frames += 1
            utime.sleep_ms(delay_ms)
        uptime += MQ_PING_INTERVAL_MS / 1000
        print("Uptime:", uptime, "FPS:", frames * 1000 // MQ_PING_INTERVAL_MS)
    except KeyboardInterrupt:
        wd.deinit()
        print("Ctrl+C pressed, exiting")
        sys.exit(1)
