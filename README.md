# Rinnai C33 Capture for Home Assistant

[中文说明](README.zh-CN.md)

Experimental Home Assistant integration for Rinnai C33 boilers using the
HF-LPB100 WiFi remote module.

This project turns Home Assistant into a transparent TCP proxy between the
Rinnai WiFi remote and the original cloud server. It can observe the raw local
traffic, expose useful states in Home Assistant, and send a small set of tested
commands back to the connected remote.

This project is not affiliated with or endorsed by Rinnai.

## Supported Features

Tested on one Rinnai C33 installation with an HF-LPB100 WiFi remote.

Supported commands:

| Home Assistant service | Meaning |
| --- | --- |
| `rinnai_c33_capture.set_dhw_temperature` | Set domestic hot water target temperature |
| `rinnai_c33_capture.set_heating` | Enable or disable heating |
| `rinnai_c33_capture.set_fast_hot_water` | Enable or disable fast hot water mode |

Exposed states:

| Entity | Meaning |
| --- | --- |
| `sensor.rinnai_c33_last_packet` | Proxy status, packet counter, last packet metadata |
| `sensor.rinnai_c33_dhw_target_temperature` | Domestic hot water target temperature |
| `switch.rinnai_c33_heating` | Low-level heating state mirror |
| `switch.rinnai_c33_fast_hot_water` | Low-level fast hot water state mirror |
| `sensor.rinnai_c33_temperature_42` | Candidate read-only temperature or status field |
| `sensor.rinnai_c33_temperature_43` | Candidate read-only temperature or status field |
| `binary_sensor.rinnai_c33_field_47` | Candidate binary runtime/status field |

Other Rinnai models, firmware versions, or regional cloud endpoints may behave
differently.

## How It Works

The HF-LPB100 module is normally configured as a TCP client. In the observed
setup it connects to:

```text
wifiboiler_s1.rinnai.com.cn:6969
```

Instead of changing the module's own server address, this integration keeps that
device setting unchanged and changes DNS resolution inside the home network:

```text
<home_assistant_ip> wifiboiler_s1.rinnai.com.cn
```

After that, the WiFi remote opens its original TCP connection to Home Assistant.
Home Assistant then opens a second TCP connection to the real upstream server
and relays bytes both ways.

```text
HF-LPB100 remote
  -> wifiboiler_s1.rinnai.com.cn:6969
  -> router DNS/hosts override
  -> Home Assistant rinnai_c33_capture:6969
  -> real Rinnai cloud server:6969
```

While relaying traffic, the integration parses frames that look like this:

```text
fa d4 <id:2> ff ff <payload_len_le:2> <field_id> <op> <size> <value...>
```

The stable observed fields are:

| Field | Meaning |
| --- | --- |
| `0x14` | Domestic hot water target temperature |
| `0x18` | Heating enable |
| `0x13` | Fast hot water |

For control, the integration writes a cloud-style command frame to the already
connected remote. For example, setting domestic hot water target temperature to
44 C sends:

```text
fa d4 9f 37 ff ff 04 00 14 0e 01 2c
```

The detailed protocol notes are in [docs/protocol.md](docs/protocol.md).

## HACS Installation

Yes, this repository is structured for HACS custom repository installation.
HACS will install the integration under Home Assistant's `custom_components`
directory.

1. Open HACS in Home Assistant.
2. Go to **Integrations**.
3. Open the three-dot menu and choose **Custom repositories**.
4. Add this repository URL:

   ```text
   https://github.com/948462448/rinnai-c33-ha
   ```

5. Choose category **Integration**.
6. Download **Rinnai C33 Capture**.
7. Restart Home Assistant.

After HACS installs the files, continue with the YAML and router DNS setup below.

## Manual Installation

Copy this directory into Home Assistant:

```text
custom_components/rinnai_c33_capture
```

The final path should look like:

```text
<config>/custom_components/rinnai_c33_capture/manifest.json
<config>/custom_components/rinnai_c33_capture/__init__.py
<config>/custom_components/rinnai_c33_capture/services.yaml
```

Restart Home Assistant after copying the files.

## Home Assistant YAML

Add this to `configuration.yaml`:

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

Configuration options:

| Option | Required | Default | Meaning |
| --- | --- | --- | --- |
| `host` | No | `0.0.0.0` | Listen address for the TCP proxy |
| `port` | No | `6969` | Listen port for the TCP proxy |
| `upstream_host` | No | `wifiboiler_s1.rinnai.com.cn` | Original cloud host name |
| `upstream_ip` | No | empty | Optional fixed IP for the upstream server |
| `upstream_port` | No | `6969` | Original cloud TCP port |
| `remote_host` | No | empty | Optional IP of the WiFi remote; used to choose the command socket |
| `log_file` | No | `rinnai_c33_capture.log` | Capture log file inside the HA config directory |

`upstream_ip` is useful when your router DNS override points the cloud domain to
Home Assistant. Without `upstream_ip`, Home Assistant may resolve the same
overridden address and accidentally connect back to itself.

## Router DNS Or Hosts Setup

Add a local DNS or hosts override on your router:

```text
<home_assistant_ip> wifiboiler_s1.rinnai.com.cn
```

Example:

```text
192.168.1.240 wifiboiler_s1.rinnai.com.cn
```

On Xiaomi or Redmi routers this can be done from the Xiaomi WiFi app's custom
Hosts page. The format is:

```text
IP domain
```

Keep a recovery path. If the remote or mobile app stops working, remove this
hosts override and restart or power-cycle the WiFi remote. The remote should
then return to the original cloud path.

## Optional UI Controls

The integration exposes low-level states and services. For normal clickable UI
controls, copy:

```text
examples/rinnai_c33_controls.yaml
```

into your Home Assistant `packages` directory, or merge it into your own
template YAML.

If you do not already use packages, add this to `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then place the example file at:

```text
<config>/packages/rinnai_c33_controls.yaml
```

Restart Home Assistant. You should then get:

| Entity | Purpose |
| --- | --- |
| `number.rinnai_dhw_target_temperature` or localized equivalent | Clickable target temperature control |
| `switch.rinnai_heating_control` or localized equivalent | Clickable heating switch |
| `switch.rinnai_fast_hot_water_control` or localized equivalent | Clickable fast hot water switch |

Home Assistant may generate localized entity IDs from the display names. Search
for `Rinnai` in Developer Tools if the exact entity IDs differ.

## Using The Services

Set domestic hot water target temperature:

```yaml
service: rinnai_c33_capture.set_dhw_temperature
data:
  temperature: 44
```

Turn heating on:

```yaml
service: rinnai_c33_capture.set_heating
data:
  enabled: true
```

Turn heating off:

```yaml
service: rinnai_c33_capture.set_heating
data:
  enabled: false
```

Turn fast hot water on:

```yaml
service: rinnai_c33_capture.set_fast_hot_water
data:
  enabled: true
```

Turn fast hot water off:

```yaml
service: rinnai_c33_capture.set_fast_hot_water
data:
  enabled: false
```

Start with harmless no-op tests, for example setting the current temperature
again, or turning off a feature that is already off.

## Verification Checklist

After restarting Home Assistant:

1. Confirm `sensor.rinnai_c33_last_packet` exists.
2. Its first state may be `listening`.
3. Restart or power-cycle the WiFi remote if it does not reconnect.
4. When connected, the sensor attributes should include a `peer` address and
   `packet_count` should increase.
5. Use a no-op service call to verify command injection.

Example states to check:

```text
sensor.rinnai_c33_last_packet
sensor.rinnai_c33_dhw_target_temperature
switch.rinnai_c33_heating
switch.rinnai_c33_fast_hot_water
```

## Standalone Tools

Run a local transparent proxy outside Home Assistant:

```bash
python3 tools/rinnai_c33_tcp_capture.py --host 0.0.0.0 --port 6969 \
  --upstream-host 123.56.82.103 --upstream-port 6969
```

Run the proxy with a tiny local control API:

```bash
python3 tools/rinnai_c33_tcp_capture.py --host 0.0.0.0 --port 6969 \
  --upstream-host 123.56.82.103 --upstream-port 6969 \
  --control-host 127.0.0.1 --control-port 6970
```

Control API examples:

```bash
curl 'http://127.0.0.1:6970/dhw?temperature=44'
curl 'http://127.0.0.1:6970/heating?enabled=0'
curl 'http://127.0.0.1:6970/fast?enabled=1'
```

Decode a captured log:

```bash
python3 tools/rinnai_c33_decode_capture.py captures/example.log
```

## Safety Notes

- This project controls heating equipment. Test carefully.
- Packet captures can contain device identifiers and household behavior.
- Do not publish raw captures unless you have reviewed and redacted them.
- Keep the router hosts override easy to undo.
- This is an experimental reverse-engineered integration, not a safety system.

## License

MIT
