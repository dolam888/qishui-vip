# 汽水音乐免费领取VIP（安卓版）

用 AScript 安卓版自动看激励广告、领取听歌时长。由 iOS 原版 [wei6718189/qishuiAScriptProject](https://github.com/wei6718189/qishuiAScriptProject) 改写为安卓实现，接口全部换成 `ascript.android.*`，并在真机上跑通。

实测环境：华为 P20（`HUAWEIEML-AL00`），Android 10，1080×2244，density 480，arm64-v8a，AScript 4.0.17。

## 功能

- 自动启动汽水音乐（`com.luna.music`），跳过开屏广告、清理会员续费弹窗
- 自动进入激励广告 → 等倒计时结束 → 点「领取成功」→ 点「领取奖励」，循环执行
- 自动关闭"直播间"形态的广告（点右上角关闭按钮，并校验是否真的关掉）
- **内置每日时间窗口**：每天 08:00–23:00 自动跑，窗口外休眠，第二天自己再开跑
- 额度用完自动进入冷却重试，确认领不到才收工，不会空转一整夜

## 目录结构

```
.
├── __init__.py          # 安卓版主脚本（AScript 工程约定，入口文件名必须是这个）
├── res/img/             # 模板图（启动图标、直播间关闭按钮等）
├── ios-original/        # iOS 原版代码备份，仅作对照，勿直接使用
│   ├── __init__.py
│   ├── README-原版.md
│   └── 来源说明.md       # 出处、作者、对应提交
├── .vscode/settings.json
└── .gitignore
```

`ios-original/` 里的代码只写了 `ascript.ios.*` 接口，依赖 iPhone 的 WebDriverAgent，Windows 和安卓都跑不起来，仅用于 diff 对照（版权归原作者 wei6718189，详见该目录的 `来源说明.md`）。

## 安装到手机

1. 手机装 **AScript 64 位版**（https://ascript.cn/docs/android/download/ ），运行模式选「无障碍模式」
2. 把这个目录整体放到手机的 `/sdcard/airscript/model/` 下，目录名随意（如 `qishuiAndroid`），`__init__.py` 必须在根
3. AScript 里开三样权限：**无障碍**、**悬浮窗**、**图色权限**
4. 打开汽水音乐并登录，然后在小程序列表点播放键

> 工程目录是纯文件夹，可以直接用手机克隆/华为分享整体拷到另一台同型号手机。但每台机器都要重新装 AScript、重新开无障碍与图色权限，并登录自己的汽水音乐账号。别用同一账号在两台手机上同时刷。

## 关键实现说明

| 项目 | 说明 |
| --- | --- |
| 命名空间 | `ascript.ios.*` → `ascript.android.*` |
| 启动 App | `system.open("com.luna.music")` |
| 屏幕尺寸 | `Device.display()`，失败时截图兜底 |
| OCR | **不要用 `Ocr.paddleocr`**：它在麒麟 970 / Android 10 上会因 `libOcrLite.so` 原生层 abort（SIGABRT），Python 层 try/except 拦不住。本项目改用 `Ocr.mlkitocr_v2()` 全屏识别 + 本地按区域/正则过滤，带 1.2 秒结果缓存与限速 |
| 返回值差异 | 安卓侧 OCR 返回对象（属性访问），iOS 侧返回 dict，已统一转换 |
| 控件查找 | `Selector().label()` → `Selector(mode=2).text()/.desc()` |
| 通知 | `notify()` → `system.toast()`（部分版本无此属性，已 try/except 兜底） |
| 直播间关闭 | 直接点固定坐标 `(0.91w, 0.073h)`，点完校验「更多直播」是否消失，失败重试 |
| 点击通道 | 无障碍 `action.click`，不需要 HID 外设 |

## 配置（`__init__.py` 开头）

| 常量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_PACKAGE` | `com.luna.music` | 汽水音乐安卓包名 |
| `DAILY_RUN_ENABLED` | `True` | 是否启用每日时间窗口 |
| `DAILY_START_HOUR` / `DAILY_START_MINUTE` | `8` / `0` | 每天几点开始跑 |
| `DAILY_STOP_HOUR` / `DAILY_STOP_MINUTE` | `23` / `0` | 每天几点收工 |
| `COOLDOWN_MINUTES` | `20` | 疑似额度用完时的冷却时长 |
| `COOLDOWN_TRIES` | `3` | 冷却后仍失败几次判定当日额度用完 |
| `MAX_LOOP_COUNT` | `0` | 0 = 不限轮次，靠时间窗口控制 |
| `MAX_IDLE_ROUNDS` | `10` | 连续多少轮没广告进入冷却 |
| `OCR_ENGINE` | `mlkit` | 保持 mlkit，paddle 会崩 |
| `_SELECTOR_MODE` | `2` | 无障碍控件检索模式，取不到可改 `3` / `0` / `1` |

## 已知限制（都是实测出来的，不是猜的）

1. **AScript 没有"定点定时启动"**。开发者页只有「开机自启动」「停止 5 秒后自启」「音量键启动上次运行」，云控定时需要开发者账号。所以"每天定时"是做在脚本内部的：只要脚本启动过一次且没被杀，它会自己按时间窗口每天开跑。
2. **锁屏会阻断自动化**。重启后 AScript 能自己启动、无障碍和截屏授权都保留，但停在锁屏界面脚本就动不了。想完全无人值守，需要在系统里关掉锁屏（设置 → 安全和隐私 → 锁屏和密码 → 直接进入桌面），这会降低手机安全性，请自行权衡。
3. **图色权限按会话生效**。AScript 进程被杀后重启，通常需要再点一次「允许录制屏幕」。
4. 华为 EMUI 下无障碍有时会出现"已启用但未绑定"，需要在系统无障碍页把开关关一次再开。建议在手机管家 → 应用启动管理里把 AScript 设为**手动管理**，自启动/关联启动/后台活动三项全开，并加入电池优化白名单。
5. 每天领取有上限，跑满后脚本会在冷却后判定收工并睡到第二天，属正常。

## 合规提醒

汽水音乐用户协议通常禁止自动化脚本刷奖励，账号存在被风控、限流的风险。本项目仅供学习交流，是否使用请自行判断，风险自负。
