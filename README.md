# Rinnai C33 Capture for Home Assistant

Experimental Home Assistant TCP proxy and control helper for Rinnai C33 boilers
that use an HF-LPB100 WiFi remote module.

This project is based on LAN traffic observed between the WiFi remote and
`wifiboiler_s1.rinnai.com.cn:6969`. It is not affiliated with or endorsed by
Rinnai.

## What It Does

- Listens on a local TCP port, usually `6969`.
- Proxies the boiler WiFi remote to the original cloud server.
- Records raw packets to a Home Assistant log file.
- Exposes basic Home Assistant states for:
  - domestic hot water target temperature
  - heating on/off
  - fast hot water on/off
  - a few read-only candidate status fields
- Registers services to send supported control commands back to the connected
  WiFi remote.

## Current Status

This is a proof-of-concept integration. It has been tested on one Rinnai C33
installation with an HF-LPB100 WiFi remote. Other boilers, firmware versions, or
regional cloud endpoints may behave differently.

Supported commands:

| Service | Meaning |
| --- | --- |
| `rinnai_c33_capture.set_dhw_temperature` | Set domestic hot water target temperature |
| `rinnai_c33_capture.set_heating` | Enable or disable heating |
| `rinnai_c33_capture.set_fast_hot_water` | Enable or disable fast hot water |

## How The Network Path Works

The HF-LPB100 remote is normally configured as a TCP client for:

```text
wifiboiler_s1.rinnai.com.cn:6969
```

The easiest non-invasive setup is to keep that device setting unchanged and add
a router DNS or hosts override:

```text
<home_assistant_ip> wifiboiler_s1.rinnai.com.cn
```

Home Assistant then listens on port `6969` and forwards traffic to the real
cloud endpoint. If your router override is global, phones on the same WiFi may
also hit the proxy. That is expected for a transparent TCP proxy, but remove the
override if you need an immediate fallback to the original cloud path.

## Installation

Copy this folder into Home Assistant:

```text
custom_components/rinnai_c33_capture
```

Then add YAML like this:

```yaml
rinnai_c33_capture:
  host: 0.0.0.0
  port: 6969
  upstream_host: wifiboiler_s1.rinnai.com.cn
  upstream_ip: 123.56.82.103
  upstream_port: 6969
  remote_host: 192.168.1.90
  log_file: rinnai_c33_capture.log
```

`remote_host` is optional. When set, Home Assistant will prefer that connected
peer when sending control commands.

Restart Home Assistant after installing the integration.

## Optional UI Controls

The integration creates low-level state entities and services. For clickable
Home Assistant controls, copy the example package:

```text
examples/rinnai_c33_controls.yaml
```

into your Home Assistant `packages` directory, or adapt it into your own YAML.

## Tools

Two standalone tools are included:

```bash
python3 tools/rinnai_c33_tcp_capture.py --host 0.0.0.0 --port 6969 \
  --upstream-host 123.56.82.103 --upstream-port 6969

python3 tools/rinnai_c33_decode_capture.py captures/example.log
```

The first command runs a local TCP proxy. The second decodes captured frames
into TLV-like field triples.

## Safety Notes

- This project controls heating equipment. Test with harmless no-op commands
  first, such as setting the current temperature again or turning off a mode that
  is already off.
- Packet captures can contain device identifiers and household behavior. Do not
  publish raw captures unless you have reviewed and redacted them.
- Keep a way to undo your router DNS or hosts override. Removing it should return
  the WiFi remote to the original cloud path.

## License

MIT
