"""
Support for Xiaomi Yeelight Wifi color bulb.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/light.yeelight/
"""
import logging
import socket

import voluptuous as vol

from homeassistant.util.color import color_temperature_mired_to_kelvin
from homeassistant.const import CONF_DEVICES, CONF_NAME, STATE_OFF
from homeassistant.components.light import (
    ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ATTR_TRANSITION, ATTR_COLOR_TEMP,
    ATTR_FLASH, FLASH_SHORT, FLASH_LONG,
    SUPPORT_BRIGHTNESS, SUPPORT_RGB_COLOR, SUPPORT_TRANSITION,
    SUPPORT_COLOR_TEMP, SUPPORT_FLASH,
    Light, PLATFORM_SCHEMA)
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = ['yeelight==0.1.0']

_LOGGER = logging.getLogger(__name__)

CONF_TRANSITION = "transition"
DEFAULT_TRANSITION = 350

CONF_SAVE_ON_CHANGE = "save_on_change"
CONF_MODE_MUSIC = "use_music_mode"

DOMAIN = 'yeelight'

DEVICE_SCHEMA = vol.Schema({
    vol.Optional(CONF_NAME): cv.string,
    vol.Optional(CONF_TRANSITION, default=DEFAULT_TRANSITION): cv.positive_int,
    vol.Optional(CONF_MODE_MUSIC, default=False): cv.boolean,
    vol.Optional(CONF_SAVE_ON_CHANGE, default=True): cv.boolean,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Optional(CONF_DEVICES, default={}): {cv.string: DEVICE_SCHEMA}, })

COLOR_SUPPORTS = (SUPPORT_RGB_COLOR |
                  SUPPORT_COLOR_TEMP)

SUPPORTS = (SUPPORT_BRIGHTNESS |
            SUPPORT_TRANSITION |
            SUPPORT_FLASH)


def _cmd(func):
    """A wrapper to catch exceptions from the bulb."""
    def _wrap(self, *args, **kwargs):
        import yeelight
        try:
            _LOGGER.debug("Calling %s with %s %s", func, args, kwargs)
            return func(self, *args, **kwargs)
        except yeelight.BulbException as ex:
            _LOGGER.error("Error when calling %s: %s", func, ex)

    return _wrap


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Yeelight bulbs."""
    lights = []
    if discovery_info is not None:
        _LOGGER.debug("Adding autodetected %s", discovery_info['hostname'])

        # not using hostname, as it seems to vary.
        name = "yeelight_%s_%s" % (discovery_info["device_type"],
                                   discovery_info["properties"]["mac"])
        device = {'name': name, 'ipaddr': discovery_info['host']}

        default_config = DEVICE_SCHEMA({'transition': DEFAULT_TRANSITION})
        lights.append(YeelightLight(device, default_config))
    else:
        for ipaddr, device_config in config[CONF_DEVICES].items():
            _LOGGER.debug("Adding configured %s", device_config[CONF_NAME])

            device = {'name': device_config[CONF_NAME], 'ipaddr': ipaddr}
            lights.append(YeelightLight(device, device_config))

    add_devices(lights)


class YeelightLight(Light):
    """Representation of a Yeelight light."""

    def __init__(self, device, config):
        """Initialize the light."""
        self.config = config
        self._name = device['name']
        self._ipaddr = device['ipaddr']

        self._supported_features = SUPPORTS
        self.__bulb = None
        self.__properties = None

    @property
    def supported_features(self):
        """Flag supported features."""
        return self._supported_features

    @property
    def unique_id(self):
        """Return the ID of this light."""
        return "{}.{}".format(self.__class__, self._ipaddr)

    @property
    def color_temp(self):
        """Return the color temperature."""
        return self._properties.get("color_temp", None)

    @property
    def name(self):
        """Return the name of the device if any."""
        return self._name

    @property
    def is_on(self):
        """Return true if device is on."""
        if self._properties.get("power", STATE_OFF) == STATE_OFF:
            return False
        return True

    @property
    def brightness(self):
        """Return the brightness of this light between 1..255."""
        bright = self._properties.get("bright", None)
        if bright:
            return 255 * (int(bright) / 100)

        return None

    @property
    def rgb_color(self):
        """Return the color property."""
        rgb = self._properties.get("rgb", None)
        if rgb is None:
            return None

        rgb = int(rgb)
        blue = rgb & 0xff
        green = (rgb >> 8) & 0xff
        red = (rgb >> 16) & 0xff

        return red, green, blue

    @property
    def _properties(self):
        return self._bulb.last_properties

    @property
    def _bulb(self):
        import yeelight
        if self.__bulb is None:
            try:
                self.__bulb = yeelight.Bulb(self._ipaddr)
                self.__bulb.get_properties()  # force init for type

                btype = self.__bulb.bulb_type
                if btype == yeelight.BulbType.Color:
                    self._supported_features |= COLOR_SUPPORTS
            except (yeelight.BulbException, socket.error) as ex:
                _LOGGER.error("Failed to connect to bulb %s, %s: %s",
                              self._ipaddr, self._name, ex)

        return self.__bulb

    def set_music_mode(self, mode):
        """Set the music mode on or off."""
        if mode:
            self._bulb.start_music()
        else:
            self._bulb.stop_music()

    def update(self):
        """Update properties from the bulb."""
        self._bulb.get_properties()

    @_cmd
    def set_brightness(self, brightness, duration):
        """Set bulb brightness."""
        if brightness:
            _LOGGER.debug("Setting brightness: %s", brightness)
            self._bulb.set_brightness(brightness / 255 * 100,
                                      duration=duration)

    @_cmd
    def set_rgb(self, rgb, duration):
        """Set bulb's color."""
        if rgb and self.supported_features & SUPPORT_RGB_COLOR:
            _LOGGER.debug("Setting RGB: %s", rgb)
            self._bulb.set_rgb(rgb[0], rgb[1], rgb[2], duration=duration)

    @_cmd
    def set_colortemp(self, colortemp, duration):
        """Set bulb's color temperature."""
        if colortemp and self.supported_features & SUPPORT_COLOR_TEMP:
            temp_in_k = color_temperature_mired_to_kelvin(colortemp)
            _LOGGER.debug("Setting color temp: %s K", temp_in_k)

            self._bulb.set_color_temp(temp_in_k, duration=duration)

    @_cmd
    def set_default(self):
        """Set current options as default."""
        self._bulb.set_default()

    @_cmd
    def set_flash(self, flash):
        """Activate flash."""
        if flash:
            from yeelight import RGBTransition, SleepTransition, Flow
            if self._bulb.last_properties["color_mode"] != 1:
                _LOGGER.error("Flash supported currently only in RGB mode.")
                return

            transition = self.config[ATTR_TRANSITION]
            if flash == FLASH_LONG:
                count = 1
                duration = transition * 5
            if flash == FLASH_SHORT:
                count = 1
                duration = transition * 2

            red, green, blue = self.rgb_color

            transitions = list()
            transitions.append(
                RGBTransition(255, 0, 0, brightness=10, duration=duration))
            transitions.append(SleepTransition(
                duration=transition))
            transitions.append(
                RGBTransition(red, green, blue, brightness=self.brightness,
                              duration=duration))

            # from pprint import pformat as pf
            # _LOGGER.error(pf(transitions))

            flow = Flow(count=count, transitions=transitions)
            self._bulb.start_flow(flow)

    def turn_on(self, **kwargs):
        """Turn the bulb on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        colortemp = kwargs.get(ATTR_COLOR_TEMP)
        rgb = kwargs.get(ATTR_RGB_COLOR)
        flash = kwargs.get(ATTR_FLASH)

        # white bulb has problems with duration > 9000, doesn't always start
        transition = self.config["transition"]
        duration = min(kwargs.get(ATTR_TRANSITION, transition), 9000)
        self._bulb.turn_on(duration=duration)

        if self.config[CONF_MODE_MUSIC] and not self._bulb.music_mode:
            self.set_music_mode(self.config[CONF_MODE_MUSIC])

        # values checked for none in methods
        self.set_rgb(rgb, duration)
        self.set_colortemp(colortemp, duration)
        self.set_brightness(brightness, duration)
        self.set_flash(flash)

        # saving current settings to the bulb if not flashing
        if not flash and self.config[CONF_SAVE_ON_CHANGE]:
            self.set_default()

    def turn_off(self, **kwargs):
        """Turn off."""
        self._bulb.turn_off()
