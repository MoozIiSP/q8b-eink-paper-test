# Linux GPIO 驱动 GDEH037E01（E Ink Spectra 6）

通用 Linux **用户态** Python 驱动，通过 libgpiod 2.x 操作 GPIO，软件模拟 4-wire SPI Mode 0、MSB first。面向首次点屏，不需要 spidev 或专用内核模块。照片画布和原始传输帧均为横向 720×480，每行 360 字节；竖屏仅作为显示方向转换。六色、4bpp，一帧 172800 字节。

## Web 管理与新算法

已增加[Web 管理端](docs/web-manager.md)：上传图片、六色预览、刷新/刷白/色条与任务状态。支持无抖动、Floyd–Steinberg、Atkinson 蛇形误差扩散、Bayer 有序抖动，以及照片增强和精细色彩调节；刷新策略加入成功帧去重、持久化 150 秒间隔及串行执行，故障排查版使用明确的 GPIO 写入顺序，并验证刷新 BUSY 忙→就绪过程。面板仍使用原厂全刷波形，不宣称支持快速局刷。

```sh
.venv/bin/python -m pip install -r requirements-web.txt
.venv/bin/python -m e6.web
```

打开 `http://127.0.0.1:8080`，默认模拟模式；Q8B 实际控制加 `--hardware`，详见上方文档。

## Radxa Dragon Q8B

目标板为 Q8B。已按官方 GPIO 文档提供[建议接线表](docs/q8b-wiring.md)和 `scripts/q8b-display.sh`，采用 `/dev/gpiochip4`，支持按实际系统覆盖控制器。按接线表连接并核对 GPIO 模式后，运行 `sudo ./scripts/q8b-display.sh --bars`。这套映射尚待实板验证。

## 硬件与接线

当前使用 **DESPI 八针接口：BUSY、RES、DC、CS、SCLK、SDI、GND、3V3**。实际连接 Q8B 请使用[DESPI 接线表](docs/q8b-wiring.md)，其中 RES/SCLK/SDI 分别对应程序的 rst/clk/mosi，3V3 接 Q8B 物理针脚 17 或 1。

### 裸屏规格参考（不是 DESPI 八针接线表）

需要带有匹配升压和外围电路的 GDEH037E01 驱动板，裸屏不能仅靠六根 GPIO 供电工作。按 `docs/GDEH037E01.pdf` 第 8–9 页参考电路核对硬件。第 10 页规定 VDD 工作范围 2.4–3.6 V；板卡 I/O 电平必须匹配，不能把绝对最大额定值当作工作电压。共地，断电接线，BS0 拉低选择四线 SPI。

| 信号 | 屏幕 FPC 引脚 | Linux 方向 | 含义 |
| --- | --- | --- | --- |
| SDA / MOSI | 14 | 输出 | SPI 数据，不需要 MISO |
| SCL / CLK | 13 | 输出 | 时钟，空闲低 |
| CSB | 12 | 输出 | 低有效 |
| DC | 11 | 输出 | 0 命令、1 数据 |
| RST_N | 10 | 输出 | 低有效复位 |
| BUSY | 9 | 输入 | 默认 0 忙，1 就绪 |
| BS0 | 8 | 固定低电平 | 四线 SPI |
| GND | 17 | 电源地 | 与主板共地 |

表中为裸屏 FPC 编号，驱动板排针编号可能不同。程序参数是 `/dev/gpiochipN:line_offset`，不是 FPC 编号、物理排针编号或旧式全局 GPIO 编号。使用 `gpiodetect`、`gpioinfo` 和板卡原理图确定映射，并确认 pinmux 已切换为 GPIO。不同信号可以使用不同 gpiochip；同一物理 GPIO 不应通过路径别名重复指定。

**BUSY 文档矛盾：** 规格第 7 页表格写低电平忙，第 8 页 Note 6-4 写高电平忙。两份参考程序均默认低电平忙，因此本程序默认 `--busy-level 0`。仅在硬件确认后才使用 `--busy-level 1`。不会自动反转极性或忽略超时；BUSY 悬空/卡在就绪电平无法靠软件轮询检测，需实测接线和波形。

## 安装与运行

要求 Linux 内核 GPIO character device v2（通常内核 5.10+，需启用 GPIO cdev）及 Python 3.9+。目标板运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

部分发行版也提供 libgpiod 2.x Python 包，旧的 1.x 接口不兼容。运行用户需有对应 `/dev/gpiochip*` 的读写权限。

先离线验证，不需要安装 gpiod，也不访问 GPIO：

```sh
python3 -m e6 --bars --dry-run
python3 -m unittest discover -s tests -v
```

下面的 **11/12/2/3/4/5 仅为参数示例，不代表目标板接线**，必须替换：

```sh
sudo .venv/bin/python -m e6 \
  --mosi /dev/gpiochip0:11 --clk /dev/gpiochip0:12 \
  --cs /dev/gpiochip0:2 --dc /dev/gpiochip0:3 \
  --rst /dev/gpiochip0:4 --busy /dev/gpiochip0:5 \
  --bars
```

将 `--bars` 换成 `--solid white` 刷白，或 `--image frame.bin` 显示原始图像。纯色支持 black、white、yellow、red、blue、green。每次运行刷新一帧后关闭面板高压并进入深睡眠，图像保持；再次运行会硬件复位。程序不控制驱动板 VDD 电源开关。

`--half-period-us` 默认 5，表示软件每半周期至少等待 5 微秒，理论上限 100 kHz；GPIO ioctl、Python 和 Linux 调度会使实际速度明显更慢且不恒定。一帧约 138 万位，传输可能耗时数十秒或更久。此实现用于通用点屏验证，对速度有要求时可后续增加硬件 SPI 后端，面板协议代码保持复用。现有 PDF 没有完整 SPI AC 时序表，首板需用逻辑分析仪核对时钟、建立/保持时间及 BUSY 响应。

## 帧格式与协议

原始传输帧逐行 **720 像素、共 480 行，每行 360 字节**；每字节高半字节为前一个像素、低半字节为后一个像素。色码：黑 0、白 1、黄 2、红 3、蓝 5、绿 6。例如 `0x31` 为红/白两个像素。Web 横屏直接按行打包，不再旋转；竖屏 480×720 顺时针旋转 90° 后打包，预览执行逆变换。旧版原始 bin 文件按 480 行宽编码，必须重新生成，长度相同不代表格式兼容。

本次扫描修正依据用户定位图中的规则重复、条纹混色，以及另一份明确标注 GDEH037E01 的[公开驱动](https://github.com/kirmisaki/FrameFilm/blob/63dba82ab82106ace50ab7dffca3c600f042631b/firmware/frame_film/components/film_hal/src/hal_epd_370.c)中每行 `720/2=360` 字节的定义。它是第三方实现，不是厂家实测认证；仍需本机定位图验证。`refs/` 保留原样，其中 480×720 注释与本次修正不同。

普通初始化与命令来源：`refs/main/GDEH037E01_idf.c`、`refs/GDEH037E01.ino`。

1. 上电稳定等待 300 ms；RST 低 20 ms、高 20 ms；等待就绪。
2. `E9 01` 普通初始化。
3. `10` 后等待就绪，写入一帧数据。
4. `04` 开启高压，等待 BUSY 就绪。
5. `12 00` 刷新，等待 BUSY 就绪。
6. `02 00` 关闭高压，等待 BUSY 就绪。
7. `07 A5` 深睡眠。

初始化/写帧前就绪超时 15 秒，高压开关超时 60 秒，刷新超时 120 秒。高压开关和刷新命令后先延时 10 ms，再检查 BUSY，给状态切换留出时间。传输遵循示例逐字节拉低/拉高 CS。任何异常停止后续命令并释放 GPIO；未知忙状态下不盲目发送关机命令。因此异常退出不保证面板高压已关闭，应检查 BUSY 和供电再恢复。进程释放 GPIO 后的电平由内核/板级偏置决定，需要硬件保证 CS 等信号的空闲状态。

未启用示例中的测试模式“水波纹”寄存器。示例命名 JD7601，而规格图纸写 IST7601，规格参数表 IC 又为 TBD；本实现限定于当前参考资料对应的 GDEH037E01，不能据此宣称兼容所有 E6 屏。

`docs/E6_design_notice-cn.pdf` 第 3 页建议连续翻页间隔 150 秒；应用层应遵循该建议，本工具不跨进程记录刷新间隔。长期存储刷白，维护刷新按产品要求安排。

## 验证状态

已提供离线测试：帧长度/色码、命令和数据顺序、各阶段超时中止、BUSY 两种极性、软件 SPI 上升沿位序及逐字节 CS。尚未在真实 Linux GPIO 和面板上验证。目标板已确定为 Radxa Dragon Q8B，并已提供基于官方文档的建议 GPIO 映射；待确认内核版本、驱动板型号及实际接线后完成板级联调。
