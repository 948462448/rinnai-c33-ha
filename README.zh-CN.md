# 林内 C33 Home Assistant 接入

这是一个实验性的 Home Assistant 集成，用于接入带 HF-LPB100 WiFi 遥控模块的林内 C33 壁挂炉。

它的核心思路是让 Home Assistant 充当林内 WiFi 遥控器和原厂云端之间的透明 TCP 代理。这样既不需要改壁挂炉本体，也不需要替换遥控模块；Home Assistant 可以在转发流量的同时读取状态，并向已经连接上的遥控器发送少量已验证过的控制命令。

本项目不是林内官方项目，也没有得到林内官方背书。

## 当前能力

目前只在一台林内 C33 + HF-LPB100 WiFi 遥控器上实测过。其他型号、固件版本、云端地址或地区版本可能不一样。

已验证的控制服务：

| Home Assistant 服务 | 作用 |
| --- | --- |
| `rinnai_c33_capture.set_dhw_temperature` | 设置生活热水目标温度 |
| `rinnai_c33_capture.set_heating` | 开关采暖 |
| `rinnai_c33_capture.set_fast_hot_water` | 开关快速热水 |

集成会暴露这些底层状态实体：

| 实体 | 说明 |
| --- | --- |
| `sensor.rinnai_c33_last_packet` | 代理状态、连接信息、包计数、最后一包元数据 |
| `sensor.rinnai_c33_dhw_target_temperature` | 生活热水目标温度 |
| `switch.rinnai_c33_heating` | 采暖状态镜像 |
| `switch.rinnai_c33_fast_hot_water` | 快速热水状态镜像 |
| `sensor.rinnai_c33_temperature_42` | 候选只读温度或状态字段 |
| `sensor.rinnai_c33_temperature_43` | 候选只读温度或状态字段 |
| `binary_sensor.rinnai_c33_field_47` | 候选二进制运行状态字段 |

注意：这些 `switch.rinnai_c33_*` 是低层状态镜像，不一定适合直接放到概览里点击。建议使用后面提供的 template 示例创建真正可点的 UI 控件。

## 原理

HF-LPB100 WiFi 遥控模块通常以 TCP Client 方式连接原厂云端。实测设备连接的是：

```text
wifiboiler_s1.rinnai.com.cn:6969
```

这个集成不改遥控器自身的服务器配置，而是在家庭网络里改 DNS 或 Hosts 解析：

```text
<Home Assistant 的 IP> wifiboiler_s1.rinnai.com.cn
```

这样遥控器仍然以为自己在连接原厂域名，但实际 TCP 连接会打到 Home Assistant。Home Assistant 在本地监听 `6969` 端口，收到遥控器连接后，再主动连接真正的林内云端服务器，并把两边字节流互相转发。

链路大概是这样：

```text
HF-LPB100 遥控器
  -> wifiboiler_s1.rinnai.com.cn:6969
  -> 路由器 DNS/Hosts 改写
  -> Home Assistant rinnai_c33_capture:6969
  -> 真正的林内云端服务器:6969
```

代理转发时，集成会解析观察到的协议帧。当前看到的帧结构类似：

```text
fa d4 <id:2> ff ff <payload_len_le:2> <field_id> <op> <size> <value...>
```

目前比较稳定的字段：

| 字段 | 含义 |
| --- | --- |
| `0x14` | 生活热水目标温度 |
| `0x18` | 采暖开关 |
| `0x13` | 快速热水 |

例如把生活热水目标温度设置为 44 C 时，云端发给遥控器的命令帧是：

```text
fa d4 9f 37 ff ff 04 00 14 0e 01 2c
```

其中 `0x2c` 就是十进制 `44`。更详细的协议记录在 [docs/protocol.md](docs/protocol.md)。

## HACS 安装

这个仓库已经按 HACS 自定义集成的结构整理好，可以作为 HACS 自定义仓库安装。

1. 打开 Home Assistant 的 HACS。
2. 进入 **Integrations**。
3. 点右上角三个点，选择 **Custom repositories**。
4. Repository 填：

   ```text
   https://github.com/948462448/rinnai-c33-ha
   ```

5. Category 选择 **Integration**。
6. 添加后搜索并下载 **Rinnai C33 Capture**。
7. 重启 Home Assistant。

HACS 只负责把自定义集成文件下载到 `custom_components`。下载完成后，还需要继续配置下面的 YAML 和路由器 Hosts。

## 手动安装

如果不用 HACS，也可以手动复制：

```text
custom_components/rinnai_c33_capture
```

放到 Home Assistant 配置目录下，最终路径类似：

```text
<config>/custom_components/rinnai_c33_capture/manifest.json
<config>/custom_components/rinnai_c33_capture/__init__.py
<config>/custom_components/rinnai_c33_capture/services.yaml
```

复制后重启 Home Assistant。

## Home Assistant 配置

在 `configuration.yaml` 里加入：

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

配置项说明：

| 配置项 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | 否 | `0.0.0.0` | Home Assistant 本地监听地址 |
| `port` | 否 | `6969` | Home Assistant 本地监听端口 |
| `upstream_host` | 否 | `wifiboiler_s1.rinnai.com.cn` | 原厂云端域名 |
| `upstream_ip` | 否 | 空 | 原厂云端固定 IP |
| `upstream_port` | 否 | `6969` | 原厂云端 TCP 端口 |
| `remote_host` | 否 | 空 | WiFi 遥控器 IP；设置后发命令时优先使用这个连接 |
| `log_file` | 否 | `rinnai_c33_capture.log` | 抓包日志文件，位于 HA 配置目录 |

为什么建议填 `upstream_ip`：如果路由器已经把 `wifiboiler_s1.rinnai.com.cn` 解析到 Home Assistant，那么 HA 自己再解析这个域名时也可能解析到自己，形成回环。指定真实上游 IP 可以避免这个问题。

## 路由器 Hosts / DNS 配置

在路由器里加一条自定义 Hosts 或 DNS 规则：

```text
<Home Assistant 的 IP> wifiboiler_s1.rinnai.com.cn
```

示例：

```text
192.168.1.240 wifiboiler_s1.rinnai.com.cn
```

小米或 Redmi 路由器可以在小米 WiFi App 的自定义 Hosts 页面添加，格式是：

```text
IP 域名
```

建议保留恢复手段：如果遥控器或手机 App 失联，删除这条 Hosts 规则，然后重启或断电重启 WiFi 遥控器，它应该会回到原厂云端链路。

## 可选 UI 控件

集成本身提供的是低层状态实体和服务。为了在概览里更自然地点击控制，可以使用示例 template：

```text
examples/rinnai_c33_controls.yaml
```

如果你已经启用了 packages，可以把它复制到：

```text
<config>/packages/rinnai_c33_controls.yaml
```

如果还没启用 packages，在 `configuration.yaml` 里加：

```yaml
homeassistant:
  packages: !include_dir_named packages
```

然后重启 Home Assistant。重启后会生成类似这些可点控件：

| 实体 | 用途 |
| --- | --- |
| `number.rinnai_dhw_target_temperature` 或本地化后的类似实体 | 生活热水目标温度 |
| `switch.rinnai_heating_control` 或本地化后的类似实体 | 采暖开关 |
| `switch.rinnai_fast_hot_water_control` 或本地化后的类似实体 | 快速热水开关 |

Home Assistant 可能会根据显示名称自动生成不同实体 ID。如果找不到，去开发者工具里搜索 `Rinnai`。

## 服务调用示例

设置生活热水目标温度：

```yaml
service: rinnai_c33_capture.set_dhw_temperature
data:
  temperature: 44
```

打开采暖：

```yaml
service: rinnai_c33_capture.set_heating
data:
  enabled: true
```

关闭采暖：

```yaml
service: rinnai_c33_capture.set_heating
data:
  enabled: false
```

打开快速热水：

```yaml
service: rinnai_c33_capture.set_fast_hot_water
data:
  enabled: true
```

关闭快速热水：

```yaml
service: rinnai_c33_capture.set_fast_hot_water
data:
  enabled: false
```

第一次测试建议用“无变化”的命令，比如把水温设置为当前值，或者关闭一个本来就是关闭的功能。

## 验证步骤

重启 Home Assistant 后：

1. 确认 `sensor.rinnai_c33_last_packet` 存在。
2. 初始状态可能是 `listening`，表示 HA 已经在监听 6969。
3. 如果遥控器没有自动重连，可以断电重启 WiFi 遥控器。
4. 遥控器连接后，`sensor.rinnai_c33_last_packet` 的属性里应该出现 `peer`，`packet_count` 也会增长。
5. 用一个无变化服务调用验证 HA 是否能向遥控器注入命令。

常用检查实体：

```text
sensor.rinnai_c33_last_packet
sensor.rinnai_c33_dhw_target_temperature
switch.rinnai_c33_heating
switch.rinnai_c33_fast_hot_water
```

## 独立抓包工具

不用 Home Assistant，也可以单独跑透明代理：

```bash
python3 tools/rinnai_c33_tcp_capture.py --host 0.0.0.0 --port 6969 \
  --upstream-host 123.56.82.103 --upstream-port 6969
```

带一个简单本地控制 API：

```bash
python3 tools/rinnai_c33_tcp_capture.py --host 0.0.0.0 --port 6969 \
  --upstream-host 123.56.82.103 --upstream-port 6969 \
  --control-host 127.0.0.1 --control-port 6970
```

控制 API 示例：

```bash
curl 'http://127.0.0.1:6970/dhw?temperature=44'
curl 'http://127.0.0.1:6970/heating?enabled=0'
curl 'http://127.0.0.1:6970/fast?enabled=1'
```

解码抓包日志：

```bash
python3 tools/rinnai_c33_decode_capture.py captures/example.log
```

## 安全说明

- 这是控制采暖设备的实验性逆向集成，谨慎测试。
- 抓包日志可能包含设备标识和家庭使用行为，不要直接公开原始抓包。
- 路由器 Hosts 规则一定要知道怎么撤销。
- 这个项目不是安全系统，也不应该替代设备本身的安全保护。

## License

MIT
