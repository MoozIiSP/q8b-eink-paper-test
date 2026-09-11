# Radxa Dragon Q8B 接线方案

依据 [Radxa 官方 40-Pin GPIO 文档](https://docs.radxa.com/en/dragon/q8b/hardware-use/pin-gpio)（核对日期：2026-09-11）。以下是本项目建议接线，尚未实板验证，也不代表已有接线。

## DESPI 八针接口接线

按用户提供的 DESPI 丝印顺序列出。左列是驱动板接口名称，中间是 **Q8B 40-pin 排针的物理针脚号**；不使用裸屏 FPC 编号。按各自板上的针脚标识定位，不根据此表推断连接器左右方向。

| DESPI 接口 | Q8B 物理针脚 | SoC GPIO / 电源 | 程序参数 |
| --- | --- | --- | --- |
| BUSY | 16 | GPIO_68 | `--busy /dev/gpiochip4:68` |
| RES | 18 | GPIO_110 | `--rst /dev/gpiochip4:110` |
| DC | 22 | GPIO_92 | `--dc /dev/gpiochip4:92` |
| CS | 24 | GPIO_90 | `--cs /dev/gpiochip4:90` |
| SCLK | 23 | GPIO_89 | `--clk /dev/gpiochip4:89` |
| SDI | 19 | GPIO_88 | `--mosi /dev/gpiochip4:88` |
| GND | 20 | GND | 不配置 GPIO |
| 3V3 | 17（或 1） | 3.3 V 电源 | 不配置 GPIO |

RES 是低有效复位输入，SCLK 是 SPI 时钟输入，SDI 是从 Q8B 发往 DESPI 的数据输入（主机 MOSI）。现有驱动及 Web 默认 GPIO 映射与此表一致，程序参数名 `rst/clk/mosi` 分别对应 DESPI 的 `RES/SCLK/SDI`。

官方示例明确给出 GPIO_42、GPIO_175 对应 `/dev/gpiochip4` 的 line 42、175；本方案采用该控制器编号及 SoC GPIO 到 line offset 的映射。设备枚举可能随系统镜像变化，上板后用 `gpiodetect`、`gpioinfo` 核对，不能仅因存在 gpiochip4 就认定映射正确。

19/23/24 分别也支持 SPI20 MOSI/SCLK/CS0。当前程序通过 GPIO 软件模拟 SPI，**不要启用占用这些针脚的硬件 SPI20 功能**；GPIO_92 还复用 SPI20_CS2，GPIO_68 还复用 UART18_TX/SPI18_SCLK，需要确保这些功能没有占用所选针脚。物理针脚 21 的 MISO 不需要连接。

DESPI 标为 **3V3** 的接口接 Q8B 物理针脚 17 或 1 的 3.3 V，**不要接 2/4 的 5 V**。断电接线并共地。这个八针接口没有 BS0，不需要从 Q8B 额外引出 BS0；如果 DESPI 板上另有接口模式跳线，按其说明选择四线 SPI。

## 使用

在项目目录安装依赖：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

官方网页使用 `python-periphery` 演示 GPIO，本项目使用 `gpiod` 2.x，二者 API 不同。无需另装 periphery；当前驱动要求 GPIO cdev v2 支持（通常内核 5.10+），仍需在目标系统确认内核配置和 Python 包可用性。

离线检查启动脚本及帧数据（不需要 GPIO 权限，也不会触碰硬件）：

```sh
E6_PYTHON=python3 ./scripts/q8b-display.sh --bars --dry-run
```

完成接线和 GPIO 映射核对后显示色条：

```sh
sudo ./scripts/q8b-display.sh --bars
```

刷白或显示原始帧：

```sh
sudo ./scripts/q8b-display.sh --solid white
sudo ./scripts/q8b-display.sh --image frame.bin
```

以上为不同操作示例，不要连续快速执行；按 E6 设计须知建议为连续翻页留出 150 秒间隔。

脚本默认使用项目 `.venv/bin/python`，默认控制器 `/dev/gpiochip4`。如果实测控制器编号不同，可替换（下面的 gpiochipN 必须改为实际编号）：

```sh
sudo env E6_GPIOCHIP=/dev/gpiochipN ./scripts/q8b-display.sh --bars
```

也可以使用 `E6_PYTHON=/绝对路径/python3` 指定解释器。信号参数可在脚本后追加覆盖，例如 `--dc /dev/gpiochip4:111`；改线时同步更新接线记录。

BUSY 默认低电平忙。面板规格对极性的描述存在冲突，详情见根目录 README；不得通过不断尝试极性来跳过真实的忙状态。当前脚本不访问电源开关，也不自动修改设备树或 pinmux。
