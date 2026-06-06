"""TCP capture/proxy listener for a Rinnai C33 HF-LPB100 WiFi remote."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

DOMAIN = "rinnai_c33_capture"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 6969
DEFAULT_UPSTREAM_HOST = "wifiboiler_s1.rinnai.com.cn"
DEFAULT_UPSTREAM_PORT = 6969
DEFAULT_LOG_FILE = "rinnai_c33_capture.log"
DEFAULT_REMOTE_HOST = ""
STATE_ENTITY_ID = "sensor.rinnai_c33_last_packet"
DHW_TEMP_ENTITY_ID = "sensor.rinnai_c33_dhw_target_temperature"
HEATING_ENTITY_ID = "switch.rinnai_c33_heating"
FAST_HOT_WATER_ENTITY_ID = "switch.rinnai_c33_fast_hot_water"
TEMP_42_ENTITY_ID = "sensor.rinnai_c33_temperature_42"
TEMP_43_ENTITY_ID = "sensor.rinnai_c33_temperature_43"
FIELD_47_ENTITY_ID = "binary_sensor.rinnai_c33_field_47"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional("host", default=DEFAULT_HOST): cv.string,
                vol.Optional("port", default=DEFAULT_PORT): cv.port,
                vol.Optional("upstream_host", default=DEFAULT_UPSTREAM_HOST): cv.string,
                vol.Optional("upstream_port", default=DEFAULT_UPSTREAM_PORT): cv.port,
                vol.Optional("upstream_ip", default=""): cv.string,
                vol.Optional("remote_host", default=DEFAULT_REMOTE_HOST): cv.string,
                vol.Optional("log_file", default=DEFAULT_LOG_FILE): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SET_DHW_TEMPERATURE_SCHEMA = vol.Schema({vol.Required("temperature"): vol.All(vol.Coerce(int), vol.Range(min=30, max=65))})
SET_BOOLEAN_SCHEMA = vol.Schema({vol.Required("enabled"): cv.boolean})

_LOGGER = logging.getLogger(__name__)


def _printable(data: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in data)


def _parse_fields(data: bytes) -> list[tuple[int, int, bytes]]:
    fields: list[tuple[int, int, bytes]] = []
    offset = 8
    while offset + 3 <= len(data):
        field_id = data[offset]
        op = data[offset + 1]
        size = data[offset + 2]
        offset += 3
        if offset + size > len(data):
            break
        fields.append((field_id, op, data[offset : offset + size]))
        offset += size
    return fields


def _command_frame(field_id: int, value: int) -> bytes:
    return bytes([0xFA, 0xD4, 0x9F, 0x37, 0xFF, 0xFF, 0x04, 0x00, field_id, 0x0E, 0x01, value])


class RinnaiC33Capture:
    """Small asyncio TCP proxy that records raw packets in both directions."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        upstream_host: str,
        upstream_port: int,
        upstream_ip: str,
        remote_host: str,
        log_file: str,
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.upstream_ip = upstream_ip.strip()
        self.remote_host = remote_host.strip()
        self.log_path = Path(hass.config.path(log_file))
        self.server: asyncio.AbstractServer | None = None
        self.remote_writers: dict[str, asyncio.StreamWriter] = {}
        self.upstream_writers: dict[str, asyncio.StreamWriter] = {}
        self.packet_count = 0
        self.connection_count = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        _LOGGER.info(
            "Rinnai C33 proxy listening on %s:%s upstream=%s:%s connect_host=%s",
            self.host,
            self.port,
            self.upstream_host,
            self.upstream_port,
            self._upstream_connect_host,
        )
        self._set_state("listening", self._base_attrs())

    async def stop(self) -> None:
        if self.server is None:
            return
        self.server.close()
        for writer in [*self.remote_writers.values(), *self.upstream_writers.values()]:
            writer.close()
        await self.server.wait_closed()
        for writer in [*self.remote_writers.values(), *self.upstream_writers.values()]:
            await self._wait_closed(writer)
        self.remote_writers.clear()
        self.upstream_writers.clear()
        self.server = None
        self._set_state("stopped", self._base_attrs())

    @property
    def _upstream_connect_host(self) -> str:
        return self.upstream_ip or self.upstream_host

    def _base_attrs(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "upstream_host": self.upstream_host,
            "upstream_port": self.upstream_port,
            "upstream_connect_host": self._upstream_connect_host,
            "remote_host": self.remote_host,
            "packet_count": self.packet_count,
            "connection_count": self.connection_count,
            "log_file": str(self.log_path),
        }

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_name = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        self.remote_writers[peer_name] = writer
        self.connection_count += 1
        upstream_name = f"{self.upstream_host}:{self.upstream_port}"
        connect_name = f"{self._upstream_connect_host}:{self.upstream_port}"
        await self._write_log(f"CONNECT remote={peer_name} upstream={upstream_name} connect={connect_name}")
        _LOGGER.info("Rinnai C33 proxy client connected: %s upstream=%s", peer_name, connect_name)
        self._set_state(
            "connected",
            self._base_attrs()
            | {
                "peer": peer_name,
            },
        )

        upstream_reader: asyncio.StreamReader | None = None
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                self._upstream_connect_host,
                self.upstream_port,
            )
            self.upstream_writers[peer_name] = upstream_writer
            await self._write_log(f"UPSTREAM_CONNECTED remote={peer_name} upstream={connect_name}")
            remote_to_cloud = asyncio.create_task(
                self._relay(reader, upstream_writer, peer_name, "remote->cloud")
            )
            cloud_to_remote = asyncio.create_task(
                self._relay(upstream_reader, writer, peer_name, "cloud->remote")
            )
            done, pending = await asyncio.wait(
                {remote_to_cloud, cloud_to_remote},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._write_log(f"ERROR remote={peer_name} upstream={connect_name}")
            _LOGGER.exception("Rinnai C33 proxy client error from %s", peer_name)
        finally:
            if self.remote_writers.get(peer_name) is writer:
                self.remote_writers.pop(peer_name, None)
            self.upstream_writers.pop(peer_name, None)
            writer.close()
            if upstream_writer is not None:
                upstream_writer.close()
            await self._wait_closed(writer)
            if upstream_writer is not None:
                await self._wait_closed(upstream_writer)
            await self._write_log(f"DISCONNECT remote={peer_name}")
            _LOGGER.info("Rinnai C33 proxy client disconnected: %s", peer_name)

    async def _relay(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer_name: str,
        direction: str,
    ) -> None:
        while not reader.at_eof():
            data = await reader.read(4096)
            if not data:
                break
            await self._record_packet(peer_name, direction, data)
            writer.write(data)
            await writer.drain()

    async def _wait_closed(self, writer: asyncio.StreamWriter) -> None:
        try:
            await writer.wait_closed()
        except Exception:
            pass

    async def _record_packet(self, peer_name: str, direction: str, data: bytes) -> None:
        self.packet_count += 1
        hex_data = data.hex(" ")
        ascii_data = _printable(data)
        self._record_known_fields(direction, data)
        await self._write_log(
            f"DATA {direction} peer={peer_name} len={len(data)} hex={hex_data} ascii={ascii_data}"
        )
        _LOGGER.debug("Rinnai C33 %s %s len=%s hex=%s", direction, peer_name, len(data), hex_data)
        self.hass.bus.async_fire(
            "rinnai_c33_capture_packet",
            {
                "peer": peer_name,
                "direction": direction,
                "length": len(data),
                "hex": hex_data,
                "ascii": ascii_data,
                "packet_count": self.packet_count,
            },
        )
        self._set_state(
            str(self.packet_count),
            self._base_attrs()
            | {
                "peer": peer_name,
                "direction": direction,
                "length": len(data),
                "hex": hex_data,
                "ascii": ascii_data,
            },
        )

    @callback
    def _record_known_fields(self, direction: str, data: bytes) -> None:
        if len(data) < 8 or data[:2] != b"\xfa\xd4":
            return

        for field_id, op, value in _parse_fields(data):
            if len(value) == 1 and field_id == 0x14 and op in (0x06, 0x0E):
                self.hass.states.async_set(
                    DHW_TEMP_ENTITY_ID,
                    value[0],
                    {
                        "unit_of_measurement": "°C",
                        "field": "14",
                        "op": f"{op:02x}",
                        "direction": direction,
                    },
                )
            elif len(value) == 1 and field_id == 0x13 and op in (0x06, 0x0E):
                self.hass.states.async_set(
                    FAST_HOT_WATER_ENTITY_ID,
                    "on" if value[0] else "off",
                    {"field": "13", "op": f"{op:02x}", "direction": direction},
                )
            elif len(value) == 1 and field_id == 0x18 and op in (0x06, 0x0E):
                self.hass.states.async_set(
                    HEATING_ENTITY_ID,
                    "on" if value[0] else "off",
                    {"field": "18", "op": f"{op:02x}", "direction": direction},
                )
            elif len(value) == 1 and field_id == 0x42 and op == 0x06:
                self.hass.states.async_set(
                    TEMP_42_ENTITY_ID,
                    value[0],
                    {
                        "unit_of_measurement": "°C",
                        "field": "42",
                        "direction": direction,
                    },
                )
            elif len(value) == 1 and field_id == 0x43 and op == 0x06:
                self.hass.states.async_set(
                    TEMP_43_ENTITY_ID,
                    value[0],
                    {
                        "unit_of_measurement": "°C",
                        "field": "43",
                        "direction": direction,
                    },
                )
            elif len(value) == 1 and field_id == 0x47 and op == 0x06:
                self.hass.states.async_set(
                    FIELD_47_ENTITY_ID,
                    "on" if value[0] else "off",
                    {"field": "47", "direction": direction},
                )

    async def send_command(self, field_id: int, value: int) -> None:
        writer = self._command_writer
        if writer is None or writer.is_closing():
            raise HomeAssistantError("Rinnai C33 remote is not connected to the proxy")

        frame = _command_frame(field_id, value)
        writer.write(frame)
        await writer.drain()
        await self._record_packet("homeassistant", "ha->remote", frame)

    @property
    def _command_writer(self) -> asyncio.StreamWriter | None:
        if self.remote_host:
            for peer_name, writer in self.remote_writers.items():
                if peer_name.startswith(f"{self.remote_host}:") and not writer.is_closing():
                    return writer
        for writer in self.remote_writers.values():
            if not writer.is_closing():
                return writer
        return None

    async def _write_log(self, line: str) -> None:
        await self.hass.async_add_executor_job(self._write_log_sync, line)

    def _write_log_sync(self, line: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n")

    @callback
    def _set_state(self, state: str, attrs: dict[str, Any]) -> None:
        self.hass.states.async_set(STATE_ENTITY_ID, state, attrs)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    conf = config.get(DOMAIN, {})
    capture = RinnaiC33Capture(
        hass,
        conf.get("host", DEFAULT_HOST),
        conf.get("port", DEFAULT_PORT),
        conf.get("upstream_host", DEFAULT_UPSTREAM_HOST),
        conf.get("upstream_port", DEFAULT_UPSTREAM_PORT),
        conf.get("upstream_ip", ""),
        conf.get("remote_host", DEFAULT_REMOTE_HOST),
        conf.get("log_file", DEFAULT_LOG_FILE),
    )
    await capture.start()
    hass.data[DOMAIN] = capture

    async def _set_dhw_temperature(call) -> None:
        await capture.send_command(0x14, call.data["temperature"])

    async def _set_heating(call) -> None:
        await capture.send_command(0x18, 1 if call.data["enabled"] else 0)

    async def _set_fast_hot_water(call) -> None:
        await capture.send_command(0x13, 1 if call.data["enabled"] else 0)

    hass.services.async_register(
        DOMAIN,
        "set_dhw_temperature",
        _set_dhw_temperature,
        schema=SET_DHW_TEMPERATURE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "set_heating",
        _set_heating,
        schema=SET_BOOLEAN_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "set_fast_hot_water",
        _set_fast_hot_water,
        schema=SET_BOOLEAN_SCHEMA,
    )

    async def _handle_stop(event: Event) -> None:
        await capture.stop()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _handle_stop)
    return True
