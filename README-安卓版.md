# 汽水音乐自动看广告脚本 — Android 版

由 iOS 原版 `wei6718189/qishuiAScriptProject` 改写，所有接口换成 `ascript.android.*`。

## 一、和 iOS 原版的差异（改了什么）

| 项目 | iOS 原版 | 本安卓版 |
| --- | --- | --- |
| 命名空间 | `ascript.ios.*` | `ascript.android.*` |
| 启动 App | `app_start(bundle_id=...)` | `system.open("com.luna.music")` |
| 屏幕尺寸 | `screen_size()` | `Device.display()`，失败时截图兜底 |
| OCR | `Ocr.paddleocr` 返回 **dict** | `Ocr.paddleocr` 返回 **OcrText 对象**，已用 `_ocr_to_dict()` 统一转成 dict |
| OCR 引擎切换 | `"vision"` / `"paddle"` | `"paddle"`（PP-OCR V5）/ `"mlkit"`（谷歌 MLKit） |
| 找「关闭」控件 | `Selector().label("关闭")` | `Selector(mode=2).text("关闭")` / `.desc("关闭")` |
| 通知 | `notify()` | `system.toast()`，失败降级为日志 |
| 点击通道 | 需外接 HID（防 WDA 被检测） | **无障碍模式直接 `action.click`，不需要 HID** |

其余业务逻辑（5 个阶段、百分比区域、两步领奖、防误点底部下载按钮）**原样保留**。

## 二、目录结构

```
qishuiAndroid/
├── __init__.py            # 主脚本（唯一入口，AScript 工程约定必须叫这个名字）
├── res/
│   └── img/
│       ├── qishuiyinyue.png            # 汽水音乐图标（启动兜底）
│       ├── img_zhibojian-close01.png    # 直播间关闭按钮模板（iOS 裁的，见下方注意）
│       ├── logo.png / img_1785263403257.png
└── .vscode/
    └── settings.json      # 工程配置（platform=Android，deviceId 待填）
```

## 三、怎么在手机上跑起来（三步）

### 第 1 步：手机装 AScript 安卓版

用手机浏览器打开 https://ascript.cn/docs/android/download/ ，扫二维码下载 **64 位版**（2018 年后的手机都用 64 位）。

装完打开 App，首页会显示一行「开发者地址」，形如 `http://192.168.1.31:9096/`。**记住这个地址**。

### 第 2 步：开权限

AScript 里点「权限」相关入口，把这几个开开：

1. **无障碍服务**（必须，不开就没法点屏幕）
2. **悬浮窗**（可选，方便看运行状态）
3. **电池优化白名单**（建议，不然锁屏后会被系统杀掉）
4. 小米/红米还要额外开「自启动」和「后台弹出界面」

运行模式选 **无障碍模式**（不是 HID/图色模式，无障碍最稳，且能直接 `action.click`）。

### 第 3 步：把代码传上去运行

手机和电脑连同一个 Wi-Fi，电脑浏览器打开手机上那个「开发者地址」`http://192.168.x.x:9096/`，进网页 IDE：

1. 右上角「工程」→ 新建一个空工程，命名 `qishuiAndroid`
2. 把本机 `qishuiAndroid\__init__.py` 的内容全选复制，粘贴进网页 IDE 的 `__init__.py`
3. 把 `res/img/` 里的 4 张图也传进工程的 `res/img/` 目录
4. 点运行

> 也可以改用 VS Code：装 AScript 官方插件 → 「AScript: 新建 AScript 工程」会生成 `build.as` → 再把 `__init__.py` 覆盖进去。这样才有 `build.as`，才能在编辑器里直接选设备运行。

## 四、必须先知道的两件事

1. **模板图需要重裁**：`res/img/img_zhibojian-close01.png` 是从 iPhone 1284×2778 屏幕上裁的，安卓分辨率对不上，模板匹配基本命不中。脚本已做降级：模板没命中会走 OCR 识别 × 符号，所以不裁也能跑，只是慢一点。要更准就用手机截图重新裁一张替换掉。
2. **识别区域是百分比**：所有 rect 都按屏幕比例算，因此换分辨率不会整体错位。但汽水音乐**安卓版和 iOS 版的界面布局不完全一样**（比如「免」字按钮位置、弹窗位置可能有偏移）。如果跑起来发现某个阶段一直识别不到，把日志发我，我按你的机型分辨率单独调。

## 五、可以改的配置（`__init__.py` 开头）

| 常量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_PACKAGE` | `com.luna.music` | 汽水音乐安卓包名 |
| `MAX_LOOP_COUNT` | `50` | 最大循环次数（防死循环） |
| `MAX_IDLE_ROUNDS` | `10` | 连续多少轮领不到就自动退出 |
| `OCR_ENGINE` | `paddle` | 识别不准可换 `mlkit` |
| `_SELECTOR_MODE` | `2` | 控件检索模式，拿不到控件改成 `3` / `0` / `1` |

## 六、合规提醒

汽水音乐用户协议通常禁止自动化脚本刷奖励，账号存在被风控/限流的风险，请自行判断是否使用。
