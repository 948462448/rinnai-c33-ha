# Rinnai C33 / HF-LPB100 Protocol Notes

These notes summarize a small set of observed frames from a Rinnai C33 boiler
using an HF-LPB100 WiFi remote.

## Frame Shape

- Magic: `fa d4`
- Bytes 2-3: unknown checksum or message id
- Bytes 4-5: usually `ff ff`
- Bytes 6-7: little-endian payload length
- Payload: TLV-like triples of `field_id op size value...`

Observed operations:

| Op | Candidate meaning |
| --- | --- |
| `06` | device report |
| `07` | device command acknowledgement |
| `0e` | cloud command or set |
| `0f` | cloud acknowledgement or request acknowledgement |

## Stable Fields

| Field | Direction | Meaning |
| --- | --- | --- |
| `02` | device to cloud | Device or module identifier |
| `14` | cloud to device | Domestic hot water target temperature command |
| `14` | device to cloud | Domestic hot water target temperature report |
| `13` | cloud to device | Fast hot water command |
| `13` | device to cloud | Fast hot water command acknowledgement |
| `18` | cloud to device | Heating enable command |
| `18` | device to cloud | Heating command acknowledgement |

Values observed for temperature fields are direct Celsius values. For example,
`2c` means `44`.

## Candidate Read-Only Fields

| Field | Candidate meaning |
| --- | --- |
| `42` | live temperature or status value |
| `43` | live temperature or status value |
| `47` | binary heating-related runtime state |

## Known Command Samples

Domestic hot water target temperature 44 C:

```text
cloud->remote len=12 hex=fa d4 9f 37 ff ff 04 00 14 0e 01 2c
remote->cloud len=18 hex=fa d4 <id> <id> ff ff 0a 00 02 06 04 <device_id> 14 07 00
```

Heating on:

```text
cloud->remote len=12 hex=fa d4 9f 37 ff ff 04 00 18 0e 01 01
remote->cloud len=18 hex=fa d4 <id> <id> ff ff 0a 00 02 06 04 <device_id> 18 07 00
```

Heating off:

```text
cloud->remote len=12 hex=fa d4 9f 37 ff ff 04 00 18 0e 01 00
remote->cloud len=22 hex=fa d4 <id> <id> ff ff 0e 00 02 06 04 <device_id> 47 06 01 01 18 07 00
```

Fast hot water on:

```text
cloud->remote len=12 hex=fa d4 9f 37 ff ff 04 00 13 0e 01 01
remote->cloud len=18 hex=fa d4 <id> <id> ff ff 0a 00 02 06 04 <device_id> 13 07 00
```

Fast hot water off:

```text
cloud->remote len=12 hex=fa d4 9f 37 ff ff 04 00 13 0e 01 00
remote->cloud len=22 hex=fa d4 <id> <id> ff ff 0e 00 02 06 04 <device_id> 42 06 01 28 13 07 00
```
