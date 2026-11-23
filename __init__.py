# -*- coding: utf-8 -*-
"""
汽水音乐 Android 自动化脚本 — 自动看广告领取免费听歌时长
============================================================
由 iOS 版（wei6718189/qishuiAScriptProject）改写而来，接口全部换成 ascript.android.*
适配要点：
  1. 屏幕尺寸 / 启动 App / OCR / 找图 全部换成安卓 API
  2. 安卓 Ocr.paddleocr 返回 OcrText 对象（属性访问），iOS 返回 dict
     → 本脚本统一经过 _ocr_to_dict() 转成 dict，上层逻辑与 iOS 版保持一致
  3. 所有识别区域仍按屏幕百分比动态计算，适配不同安卓分辨率

技术栈：
  - OCR 文字识别：ascript.android.screen.Ocr（PaddleOCR V5 / MLKit 双引擎）
  - 图像识别兜底：ascript.android.screen.FindImages
  - 动作执行    ：ascript.android.action
  - 应用管理    ：ascript.android.system
"""

import time
import re
import traceback

# ============== 基础模块导入（安卓命名空间） ==============
from ascript.android import action
from ascript.android import screen
from ascript.android import system
from ascript.android.system import R, Device
from ascript.android.screen import Ocr, FindImages
from ascript.android.node import Selector


# ============== 全局配置 ==============
APP_NAME = "汽水音乐"
APP_PACKAGE = "com.luna.music"      # 汽水音乐安卓包名（优先，比名称稳定）

MAX_LOOP_COUNT = 0                  # 最大循环次数，0 = 不限（由每日时间窗口控制）
MAX_IDLE_ROUNDS = 10                # 连续多少轮没领到奖励后进入冷却
LOOP_INTERVAL = 3                   # 每轮间隔秒数

# ============== 每日定时（脚本内置排程，不依赖系统定时） ==============
# 原理：AScript 没有"定点定时启动"功能，所以由脚本自己看表。
# 启动一次后，它会每天在窗口内自动开跑，窗口外自动休眠，第二天自己再开跑。
DAILY_RUN_ENABLED = True
DAILY_START_HOUR = 8                # 每天开始时间（时）
DAILY_START_MINUTE = 0
DAILY_STOP_HOUR = 23                # 每天停止时间（时），避免整夜亮屏耗电
DAILY_STOP_MINUTE = 0
COOLDOWN_MINUTES = 20               # 疑似额度用完时的冷却时长（分钟）
COOLDOWN_TRIES = 3                  # 冷却后仍失败满几次，判定当日额度用完

# OCR 引擎："paddle"=PaddleOCR V5（推荐，准） / "mlkit"=谷歌 MLKit（快）
OCR_ENGINE = "mlkit"

# 运行模式常量（见下方 _ocr_mode()）
_SELECTOR_MODE = 2                  # 无障碍过滤系统控件模式，找不到可改 3 / 0 / 1

REGION_FULL = None
HAS_LIVE_ROOM_TEMPLATE = False
_SCREEN_WH = None

# OCR 限速与缓存（防原生库崩溃 + 降低识别开销）
OCR_MIN_INTERVAL = 0.6
_LAST_OCR_TS = [0.0]
OCR_CACHE_TTL = 1.2
_OCR_CACHE = {"ts": 0.0, "items": []}


# ============== 工具函数 ==============

def log(msg: str):
    """统一日志打印"""
    ts = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{ts}] {msg}")


def screen_size():
    """获取屏幕宽高（缓存一次，避免反复截图）"""
    global _SCREEN_WH
    if _SCREEN_WH:
        return _SCREEN_WH
    w = h = 0
    # 方式一：系统 API
    try:
        d = Device.display()
        w, h = int(d.widthPixels), int(d.heightPixels)
    except Exception:
        pass
    # 方式二：截图兜底
    if not w or not h:
        try:
            bmp = screen.capture()
            w, h = int(bmp.getWidth()), int(bmp.getHeight())
        except Exception:
            pass
    _SCREEN_WH = (w or 1080, h or 2400)
    return _SCREEN_WH


def _ocr_to_dict(item):
    """
    把 OCR 结果统一转成 dict。
    安卓返回 OcrText 对象（.text/.center_x/.center_y/.confidence）
    个别版本可能直接返回 dict，两种都兼容。
    """
    if isinstance(item, dict):
        return item
    return {
        "text": getattr(item, "text", "") or "",
        "center_x": int(getattr(item, "center_x", 0) or 0),
        "center_y": int(getattr(item, "center_y", 0) or 0),
        "confidence": float(getattr(item, "confidence", 0) or 0),
        "rect": getattr(item, "rect", None),
    }


def _ocr_all():
    """
    用谷歌 MLKit（mlkitocr_v2）做全屏文字识别，带 1.2 秒缓存。
    ⚠️ 不用 Ocr.paddleocr：libOcrLite.so 在本机（麒麟970/Android10）会 SIGABRT 崩溃。
    """
    now = time.time()
    if now - _OCR_CACHE["ts"] < OCR_CACHE_TTL:
        return _OCR_CACHE["items"]
    gap = now - _LAST_OCR_TS[0]
    if gap < OCR_MIN_INTERVAL:
        time.sleep(OCR_MIN_INTERVAL - gap)
    _LAST_OCR_TS[0] = time.time()
    try:
        raw = Ocr.mlkitocr_v2()
    except Exception as e:
        log(f"  mlkitocr_v2 异常: {e}")
        raw = []
    _OCR_CACHE["items"] = [_ocr_to_dict(r) for r in (raw or [])]
    _OCR_CACHE["ts"] = time.time()
    return _OCR_CACHE["items"]


def paddle_scan(rect=None, pattern=None, confidence=0.1):
    """
    兼容原调用签名：先 MLKit 全屏识别，再按 rect 和正则 pattern 本地过滤。
    返回 dict 列表（text / center_x / center_y / confidence）。
    """
    items = _ocr_all()
    if rect:
        x1, y1, x2, y2 = rect[0], rect[1], rect[2], rect[3]
        items = [i for i in items
                 if x1 <= (i.get("center_x") or 0) <= x2
                 and y1 <= (i.get("center_y") or 0) <= y2]
    if pattern:
        try:
            rx = re.compile(pattern)
            items = [i for i in items if rx.search(i.get("text") or "")]
        except Exception as e:
            log(f"  正则编译失败 '{pattern}': {e}")
            return []
    return items


def paddle_find_first(pattern, rect, log_label=""):
    """
    在指定小区域用 PaddleOCR 精准识别关键词，返回第一个有效命中 dict 或 None。
    pattern 是正则；rect = [x1, y1, x2, y2]。
    """
    try:
        results = paddle_scan(rect=rect, pattern=pattern)
        for item in results:
            cx = item.get("center_x", 0)
            cy = item.get("center_y", 0)
            if cx > 0 and cy > 0:
                if log_label:
                    log(f"  [{log_label}] '{pattern}' -> '{item.get('text','')}' "
                        f"置信度={item.get('confidence',0):.2f} ({cx},{cy})")
                return item
    except Exception as e:
        log(f"  paddle_find '{pattern}' 异常: {e}")
    return None


def safe_click(x: int, y: int, desc: str = ""):
    """安全点击：带日志 + 异常捕获"""
    try:
        log(f"点击 [{desc}] -> ({x}, {y})")
        action.click(int(x), int(y))
        time.sleep(0.8)
        return True
    except Exception as e:
        log(f"点击失败 [{desc}]: {e}")
        return False


def click_center():
    """点击屏幕中心（弹窗兜底策略）"""
    w, h = screen_size()
    safe_click(w // 2, h // 2, "屏幕中心")


def notify(msg: str):
    """安卓通知：尽量调系统 toast，失败就只打日志"""
    try:
        system.toast(msg)
        return
    except Exception:
        pass
    try:
        from ascript.android.ui import Toast
        Toast.show(msg)
        return
    except Exception:
        log(f"[通知] {msg}")


def init_regions():
    """初始化搜索区域，检查资源文件"""
    global REGION_FULL, HAS_LIVE_ROOM_TEMPLATE
    w, h = screen_size()
    log(f"屏幕尺寸: {w} x {h}")
    REGION_FULL = [0, 0, w, h]

    import os as _os
    template_path = R.img("img_zhibojian-close01.png")
    HAS_LIVE_ROOM_TEMPLATE = _os.path.exists(template_path)
    log(f"直播间关闭按钮模板图: "
        f"{'✅ 存在 ' + template_path if HAS_LIVE_ROOM_TEMPLATE else '❌ 不存在（将走 OCR 兜底）'}")


# ============== 阶段一：启动 App ==============

def launch_app() -> bool:
    """启动汽水音乐（发指令后立即返回，好让跳开屏广告立刻跟上）"""
    log("=" * 50)
    log("阶段一：启动汽水音乐 App")
    for target in (APP_PACKAGE, APP_NAME):
        if not target:
            continue
        try:
            system.open(target)
            log(f"App 启动指令已发送（{target}），立即开始监控开屏跳过...")
            return True
        except Exception as e:
            log(f"启动失败（{target}）: {e}")
    log("启动 API 全部失败，尝试找图点桌面图标...")
    return try_click_app_icon()


def try_click_app_icon() -> bool:
    """兜底：通过找图点桌面汽水音乐图标"""
    icon_path = R.img("qishuiyinyue.png")
    log(f"尝试找图点桌面图标: {icon_path}")
    try:
        for attempt in range(3):
            pos = FindImages.find(icon_path, confidence=0.8)
            if pos:
                return safe_click(pos["center_x"], pos["center_y"], "汽水音乐图标")
            log(f"  第 {attempt+1} 次未找到图标，重试...")
            time.sleep(1)
        log("未找到汽水音乐图标（" + icon_path + "），请检查模板图或屏幕内容")
        return False
    except Exception as e:
        log(f"找图点图标异常: {e}")
        return False


# ============== 阶段一 B：开屏广告跳过 ==============

def skip_splash_ad(timeout=5) -> bool:
    """
    启动 App 后检测并跳过开屏广告。
    用 PaddleOCR 在右上角小区域精准识别「跳过」，识别率高。
    rect 按屏幕比例：x:80%~97%, y:6%~10%
    """
    log("阶段一B：检测并跳过开屏广告（PaddleOCR 精准识别中...）")
    w, h = screen_size()
    rect_skip = [int(w * 0.80), int(h * 0.06), int(w * 0.97), int(h * 0.10)]

    deadline = time.time() + timeout
    scan_count = 0
    while time.time() < deadline:
        scan_count += 1
        item = paddle_find_first(r"跳过", rect_skip)
        if item:
            log(f"  [扫描#{scan_count}] 命中跳过后点击")
            safe_click(item["center_x"], item["center_y"], "开屏跳过")
            return True
        time.sleep(0.15)
    log(f"  扫描结束（共 {scan_count} 次），未检测到开屏跳过按钮")
    return False


def ocr_find_text(keywords, rect=None, timeout=0):
    """
    用 Ocr.find 在屏幕上查找匹配关键词的文字（走默认引擎，比 paddleocr 快）
    返回第一个匹配结果 dict 或 None
    """
    start = time.time()
    while True:
        try:
            for kw in keywords:
                result = Ocr.find(kw, rect=rect)
                if result:
                    result = _ocr_to_dict(result)
                    log(f"  OCR 命中关键词: '{kw}' -> '{result.get('text','')}' "
                        f"位置({result.get('center_x',0)},{result.get('center_y',0)})")
                    return result
        except Exception as e:
            log(f"  OCR 识别异常: {e}")
        if timeout <= 0 or (time.time() - start) >= timeout:
            return None
        time.sleep(0.8)


def ocr_find_mid_first(keywords):
    """
    【弹窗优先】先在屏幕中间区域（高 20%~85%）搜，找不到再全屏搜。
    避免顶部状态栏的小字先被命中。
    """
    w, h = screen_size()
    mid_rect = [0, int(h * 0.2), w, int(h * 0.85)]
    for kw in keywords:
        r = ocr_find_text([kw], rect=mid_rect)
        if r:
            log(f"  [中间区命中] '{kw}'")
            return r
    for kw in keywords:
        r = ocr_find_text([kw], rect=REGION_FULL)
        if r:
            log(f"  [全屏命中] '{kw}'")
            return r
    return None


# ============== 阶段二：弹窗清理 ==============

def close_membership_popup() -> bool:
    """
    检测并关闭"续费会员"弹窗：底部出现"元开通"文字即认定。
    处理方式：点击弹窗上方遮罩（点屏幕 y:30% 处）关闭。
    """
    w, h = screen_size()
    bottom_rect = [int(w * 0.044), int(h * 0.877), int(w * 0.953), int(h * 0.963)]
    item = paddle_find_first(r"元开通", bottom_rect, "续费会员弹窗")
    if item:
        log(f"  检测到底部 '{item.get('text','')}'，点击弹窗外部关闭")
        safe_click(int(w * 0.5), int(h * 0.30), "弹窗遮罩")
        time.sleep(1.2)
        return True
    return False


# 兼容旧调用名
check_and_back_from_membership_page = close_membership_popup


def _detect_membership_popup(rect_pay) -> bool:
    """内部辅助：底部是否出现「元开通」文字"""
    return bool(paddle_find_first(r"元开通", rect_pay))


def check_and_close_thirdparty_download() -> bool:
    """
    检测是否跳到第三方下载页（安卓上常见：应用商店/浏览器下载页）。
    判定：左上角出现"完成"/"关闭"/"×"。
    """
    w, h = screen_size()
    rect_done = [int(w * 0.02), int(h * 0.06), int(w * 0.20), int(h * 0.12)]
    item = paddle_find_first(r"完成|关闭|返回", rect_done, "第三方下载页")
    if item:
        safe_click(item["center_x"], item["center_y"], "第三方页关闭按钮")
        time.sleep(1.0)
        return True
    return False


def dismiss_popups(max_rounds=3) -> int:
    """弹窗清理：目前只处理"续费会员"弹窗"""
    log("阶段二：弹窗清理（仅处理续费会员弹窗）")
    handled = 0
    for _ in range(max_rounds):
        if close_membership_popup():
            handled += 1
            time.sleep(1.0)
            continue
        break
    if handled == 0:
        log("  未检测到续费会员弹窗，无需清理。")
    log(f"弹窗清理结束，共处理 {handled} 个")
    return handled


def light_background_cleanup() -> bool:
    """轻量背景清理：只检查续费会员弹窗"""
    return close_membership_popup()


# ============== 阶段三：监测"免"字 / 立即领取 入口 ==============

def wait_for_mian_button(timeout=60, allow_mian=True) -> bool:
    """
    监测进广告入口：
      allow_mian=True ：先搜"立即解锁/立即领取"，再搜右上角"免"字，都没有就定期清理弹窗
      allow_mian=False：只搜"立即解锁/领取"弹窗（后续轮次不再找"免"字）
    """
    log("阶段三：监测进广告入口" + ("（弹窗优先，其次'免'字）" if allow_mian else "（仅弹窗按钮）"))
    w, h = screen_size()
    rect_mian = [int(w * 0.62), int(h * 0.03), int(w * 0.95), int(h * 0.13)]
    rect_unlock = [int(w * 0.029), int(h * 0.52), int(w * 0.981), int(h * 0.982)]
    rect_pay = [int(w * 0.044), int(h * 0.877), int(w * 0.953), int(h * 0.963)]

    deadline = time.time() + timeout if timeout > 0 else 0
    check_count = 0
    last_cleanup = 0.0
    CLEANUP_INTERVAL = 8
    REVERIFY_WAIT = 0.7

    while True:
        check_count += 1

        # 1) 最高优先：立即解锁 / 立即领取
        unlock_hit = paddle_find_first(r"立即(解锁|领取)|免费畅听|免费听|领取奖励", rect_unlock, "进广告弹窗")
        if unlock_hit:
            log(f"  [扫描#{check_count}] 命中进广告按钮 → 点击")
            safe_click(unlock_hit["center_x"], unlock_hit["center_y"], "进广告按钮")
            time.sleep(1.5)
            return True

        # 2) 其次：右上角"免"字
        if allow_mian:
            mian_hit = paddle_find_first(r"免", rect_mian, "免字")
            if mian_hit:
                has_popup = _detect_membership_popup(rect_pay)
                max_retry = 2 if has_popup else 1
                log(f"  检测到续费弹窗={'是' if has_popup else '否'} → 重试上限={max_retry}")
                for attempt in range(1, max_retry + 1):
                    safe_click(mian_hit["center_x"], mian_hit["center_y"], f"'免'字(尝试{attempt})")
                    if max_retry == 1:
                        log("  [成功] 无续费弹窗，点击 1 次即进入广告")
                        time.sleep(1.0)
                        return True
                    time.sleep(REVERIFY_WAIT)
                    verify_hit = paddle_find_first(r"免", rect_mian)
                    if verify_hit is None:
                        log(f"  [成功] 点击后'免'字消失（尝试 {attempt} 次生效）")
                        time.sleep(0.8)
                        return True
                    log("  [未生效] '免'字仍在屏上，继续重试")
                log(f"  [重试耗尽] 连续 {max_retry} 次点击未触发跳转，本轮放弃")

        # 3) 都没命中 → 定期清弹窗
        now = time.time()
        if now - last_cleanup >= CLEANUP_INTERVAL:
            try:
                light_background_cleanup()
            except Exception as e:
                log(f"  背景清理异常: {e}")
            last_cleanup = now

        if timeout > 0 and time.time() >= deadline:
            log(f"  等待进广告入口超时 ({timeout}s)，本轮跳过")
            return False
        if timeout == 0:
            log("  单次检查：未发现进广告入口")
            return False
        time.sleep(0.2)


# ============== 阶段四：等待广告倒计时 ==============

def check_and_click_continue_watching() -> bool:
    """
    只点屏幕中间（y:25%~68%）的"继续观看"。
    底部那个"继续观看下载XX"是广告诱导，绝不能点。
    """
    w, h = screen_size()
    rect_continue = [int(w * 0.07), int(h * 0.25), int(w * 0.93), int(h * 0.68)]
    item = paddle_find_first(r"继续观看", rect_continue, "继续观看(中间区)")
    if item:
        if safe_click(item["center_x"], item["center_y"], "继续观看(中间区)"):
            time.sleep(2.5)
            return True
    return False


def _close_live_room(rect_close_btn) -> bool:
    """关闭直播间：安卓版关闭按钮固定在右上角 → 直接点固定坐标 + 校验，
    失败再退回 iOS 那套模板图/OCR 方案"""
    w, h = screen_size()
    fixed_x, fixed_y = int(w * 0.91), int(h * 0.073)
    rect_more_live = [int(w * 0.694), int(h * 0.099), int(w * 0.971), int(h * 0.145)]
    for attempt in range(1, 3):
        safe_click(fixed_x, fixed_y, f"直播间关闭(固定坐标{attempt})")
        time.sleep(1.6)
        if not paddle_find_first(r"更多直播", rect_more_live):
            log("  直播间已关闭（'更多直播'已消失）")
            return True
        log("  仍检测到'更多直播'，再点一次")
    return False


def _close_live_room_legacy(rect_close_btn) -> bool:
    """旧方案（iOS 模板图 → OCR 符号 → 控件兜底），保留备用"""
    # 一级：模板图
    if HAS_LIVE_ROOM_TEMPLATE:
        try:
            result = FindImages.find(R.img("img_zhibojian-close01.png"), rect=rect_close_btn)
            if result:
                log(f"  FindImages 命中关闭按钮 (置信度={result.get('confidence',0):.2f})")
                safe_click(result["center_x"], result["center_y"], "直播间关闭(模板)")
                time.sleep(1.5)
                return True
        except Exception as e:
            log(f"  FindImages 异常: {e}，改用 OCR")

    # 二级：OCR 识别 × 符号
    hit = paddle_find_first(r"[×✕✖Xx]", rect_close_btn, "关闭符号")
    if hit:
        safe_click(hit["center_x"], hit["center_y"], "关闭按钮(OCR)")
        time.sleep(1.5)
        return True

    # 三级：控件兜底（安卓无障碍，带 mode）
    try:
        node = Selector(mode=_SELECTOR_MODE).text("关闭").find()
        if node is None:
            node = Selector(mode=_SELECTOR_MODE).desc("关闭").find()
        if node:
            try:
                node.click()
            except Exception:
                r = node.rect
                safe_click((int(r.x1) + int(r.x2)) // 2, (int(r.y1) + int(r.y2)) // 2, "关闭按钮(控件)")
            time.sleep(1.5)
            log("  控件兜底点击完成")
            return True
    except Exception as e:
        log(f"  Selector 兜底异常: {e}")
    return False


def wait_ad_countdown(timeout=30) -> bool:
    """
    阶段四：等广告倒计时结束。两类广告：
      1) 视频广告：倒计时结束 → 右上角"领取成功"
      2) 直播间广告：无倒计时 → 右上角"更多直播" → 点关闭 → 出现"领取成功"
    轮询优先级：领取成功 > 直播间（需关闭） > 倒计时（仅打日志）
    """
    log("阶段四：等待广告倒计时结束（支持视频广告 & 直播间广告）")
    w, h = screen_size()
    rect_claim_top = [int(w * 0.55), int(h * 0.03), w, int(h * 0.14)]
    rect_claim_mid = [0, int(h * 0.25), w, int(h * 0.70)]
    rect_countdown = [int(w * 0.58), int(h * 0.045), int(w * 0.97), int(h * 0.09)]
    rect_live_room = [int(w * 0.092), int(h * 0.609), int(w * 0.911), int(h * 0.786)]
    rect_more_live = [int(w * 0.694), int(h * 0.099), int(w * 0.971), int(h * 0.145)]
    rect_follow = [0, int(h * 0.05), int(w * 0.56), int(h * 0.107)]
    rect_close_btn = [int(w * 0.619), int(h * 0.045), w, int(h * 0.11)]

    deadline = time.time() + timeout
    last_sec = -1
    checks = 0
    live_logged = False

    while time.time() < deadline:
        checks += 1

        # 1) 最高优先：广告结束 / 奖励弹窗（安卓版"恭喜获得VIP听歌时长"在屏幕中间）
        hit_claim = paddle_find_first(r"领取成功", rect_claim_top, "广告结束标志")
        if not hit_claim:
            hit_claim = paddle_find_first(r"恭喜获得|VIP听歌时长|广告已结束", rect_claim_mid, "奖励弹窗")
        if hit_claim:
            log(f"  检测到广告结束标志（轮询 {checks} 次）→ 交给 claim_reward")
            return True

        # 2) 次高优先：是否在直播间内
        if not live_logged:
            if paddle_find_first(r"直播间", rect_live_room, "直播间检测"):
                log(f"  检测到直播间广告（轮询 {checks} 次）→ 尝试关闭")
                live_logged = True

        more_live = paddle_find_first(r"更多直播", rect_more_live, "直播间识别")
        follow = None
        if not more_live:
            follow = paddle_find_first(r"关注", rect_follow, "关注按钮")

        if more_live or follow:
            log("  确认在直播间内 → 关闭直播间...")
            if _close_live_room(rect_close_btn):
                continue
            log("  未找到关闭按钮，本轮跳过")

        # 3) 最低优先：倒计时文案（仅打日志）
        cd = paddle_find_first(r"秒后可领奖励", rect_countdown, "倒计时")
        if cd:
            text = cd.get("text", "")
            sec = next((int(ch) for ch in text if ch.isdigit()), None)
            if sec is not None and sec != last_sec:
                log(f"  广告倒计时中... {text}")
                last_sec = sec

        time.sleep(0.8)

    log(f"  等待超时 ({timeout}s)，'领取成功'未出现（本轮可能没广告可领）")
    return False


# ============== 阶段五：领取奖励 ==============

def claim_reward() -> int:
    """
    两步领取：
      1) 点右上角"领取成功"
      2) 点中间弹窗"领取奖励" → 自动进入下一轮广告
    返回 1=成功，0=失败
    """
    log("阶段五：领取奖励（点领取成功 → 点领取奖励 → 下一轮）")
    w, h = screen_size()
    rect_claim_top = [int(w * 0.55), int(h * 0.03), w, int(h * 0.14)]
    rect_reward_btn = [int(w * 0.13), int(h * 0.25), int(w * 0.87), int(h * 0.70)]

    # 第一步
    log("  [步骤 1/2] 等右上角'领取成功'...")
    hit_claim = None
    deadline1 = time.time() + 20
    checks1 = 0
    while time.time() < deadline1:
        checks1 += 1
        hit_claim = paddle_find_first(r"领取成功", rect_claim_top)
        if not hit_claim:
            hit_claim = paddle_find_first(r"恭喜获得|VIP听歌时长|广告已结束", rect_reward_btn)
        if hit_claim:
            break
        time.sleep(0.35)
    if not hit_claim:
        log(f"  [失败] 20s 内未等到'领取成功'（轮询 {checks1} 次），本轮放弃")
        return 0
    log(f"  [命中] '领取成功' @ ({hit_claim['center_x']},{hit_claim['center_y']})")
    safe_click(hit_claim["center_x"], hit_claim["center_y"], "'领取成功'")

    # 第二步
    log("  [步骤 2/2] 等弹窗'领取奖励'...")
    time.sleep(0.6)
    hit_reward = None
    deadline2 = time.time() + 15
    checks2 = 0
    while time.time() < deadline2:
        checks2 += 1
        hit_reward = paddle_find_first(r"领取奖励|免费畅听|免费听", rect_reward_btn)
        if hit_reward:
            break
        time.sleep(0.35)
    if not hit_reward:
        log(f"  [失败] 15s 内未等到'领取奖励'弹窗（轮询 {checks2} 次），本轮放弃")
        return 0
    log(f"  [命中] '领取奖励' @ ({hit_reward['center_x']},{hit_reward['center_y']}) → 点击")
    safe_click(hit_reward["center_x"], hit_reward["center_y"], "'领取奖励'")
    time.sleep(1.5)

    log("  [成功] 两步领取完成，进入下一轮倒计时")
    return 1


# ============== 主流程 ==============

def run_ad_loop() -> int:
    """每日自动循环：窗口内跑 → 额度满则冷却 → 休到明天 → 第二天自己再开"""

    def _minutes_now():
        t = time.localtime()
        return t.tm_hour * 60 + t.tm_min

    def in_window():
        if not DAILY_RUN_ENABLED:
            return True
        start = DAILY_START_HOUR * 60 + DAILY_START_MINUTE
        stop = DAILY_STOP_HOUR * 60 + DAILY_STOP_MINUTE
        cur = _minutes_now()
        if start <= stop:
            return start <= cur < stop
        return cur >= start or cur < stop

    def secs_to_start():
        t = time.localtime()
        today_start = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday,
                                       DAILY_START_HOUR, DAILY_START_MINUTE, 0, 0, 0, -1)))
        cur = _minutes_now()
        start = DAILY_START_HOUR * 60 + DAILY_START_MINUTE
        target = today_start if cur < start else today_start + 86400
        return max(0, int(target - time.time()))

    def wait_window():
        while not in_window():
            left = secs_to_start()
            log(f"  💤 不在运行窗口（{DAILY_START_HOUR:02d}:{DAILY_START_MINUTE:02d}-"
                f"{DAILY_STOP_HOUR:02d}:{DAILY_STOP_MINUTE:02d}），"
                f"{left // 3600} 小时 {(left % 3600) // 60} 分钟后自动开始")
            slept = 0
            while slept < left:
                time.sleep(min(300, max(1, left - slept)))
                slept += 300
                if in_window():
                    return

    log("\n" + "#" * 60)
    log("🎯 进入每日自动循环")
    log(f"   运行窗口: 每天 {DAILY_START_HOUR:02d}:{DAILY_START_MINUTE:02d} - "
        f"{DAILY_STOP_HOUR:02d}:{DAILY_STOP_MINUTE:02d}")
    log("   停止方式: 按音量- 关闭程序 / 点项目停止")
    log("#" * 60)

    total = 0
    day_no = 0
    while True:
        wait_window()
        day_no += 1
        log(f"\n===== 第 {day_no} 天任务开始 @ {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
        try:
            launch_app()
            skip_splash_ad(timeout=5)
            dismiss_popups()
            wait_for_mian_button(timeout=20, allow_mian=True)
        except Exception as e:
            log(f"  ⚠️ 启动阶段异常（继续尝试）: {e}")

        success_count = 0
        round_idx = 0
        idle_count = 0
        cooldown_tries = 0
        grew_at_this_cooldown = False

        while True:
            if not in_window():
                log("  ⏰ 已到今日停止时间，收工")
                break
            if MAX_LOOP_COUNT and round_idx >= MAX_LOOP_COUNT:
                log(f"  ⏰ 已达最大轮次 {MAX_LOOP_COUNT}，今日收工")
                break

            round_idx += 1
            log(f"\n---- 第 {round_idx} 轮广告循环 ----")

            got_ad = wait_ad_countdown(timeout=30)
            if not got_ad:
                idle_count += 1
                log(f"  第 {round_idx} 轮：未检测到广告结束（连续 {idle_count}/{MAX_IDLE_ROUNDS} 轮无广告）")
                if idle_count >= MAX_IDLE_ROUNDS:
                    cooldown_tries += 1
                    log(f"  😴 疑似当日额度已用完，冷却 {COOLDOWN_MINUTES} 分钟后重试"
                        f"（第 {cooldown_tries}/{COOLDOWN_TRIES} 次）")
                    if cooldown_tries >= COOLDOWN_TRIES:
                        log("  ✅ 判定今日额度已用完，今天收工，明天自动再跑")
                        break
                    cooldown = COOLDOWN_MINUTES * 60
                    slept = 0
                    while slept < cooldown and in_window():
                        time.sleep(min(60, cooldown - slept))
                        slept += 60
                    # 冷却结束，重新拉一次 App 和入口
                    try:
                        launch_app()
                        skip_splash_ad(timeout=5)
                        dismiss_popups()
                        wait_for_mian_button(timeout=20, allow_mian=True)
                    except Exception as e:
                        log(f"  ⚠️ 冷却后启动异常: {e}")
                    round_idx = 0
                    idle_count = 0
                else:
                    time.sleep(3)
                continue

            if claim_reward() == 1:
                success_count += 1
                total += 1
                idle_count = 0
                cooldown_tries = 0
                log(f"  ✅ 第 {round_idx} 轮领取成功！今日 = {success_count}，累计 = {total}")
            else:
                idle_count += 1
                log(f"  ⚠️  第 {round_idx} 轮领取失败（连续 {idle_count}/{MAX_IDLE_ROUNDS}）")
                if idle_count >= MAX_IDLE_ROUNDS:
                    cooldown_tries += 1
                    log(f"  😴 连续失败，冷却 {COOLDOWN_MINUTES} 分钟（第 {cooldown_tries}/{COOLDOWN_TRIES} 次）")
                    if cooldown_tries >= COOLDOWN_TRIES:
                        log("  ✅ 判定今日额度已用完，今天收工，明天自动再跑")
                        break
                    cooldown = COOLDOWN_MINUTES * 60
                    slept = 0
                    while slept < cooldown and in_window():
                        time.sleep(min(60, cooldown - slept))
                        slept += 60
                    round_idx = 0
                    idle_count = 0
                    continue

            time.sleep(LOOP_INTERVAL / 3 or 1)

        log(f"\n📊 第 {day_no} 天结束：今日领取 {success_count} 次，累计 {total} 次"
            f"，明天 {DAILY_START_HOUR:02d}:{DAILY_START_MINUTE:02d} 自动继续")

    return total


def main():
    """脚本入口"""
    log("🎵 汽水音乐自动看广告脚本（Android 版）启动")
    log("   流程：启动 App → 跳开屏广告 → 检测进广告入口 → 无限循环领奖励")
    try:
        init_regions()
        try:
            Ocr.set_engine("mlkit")
            log("OCR 引擎: MLKit（mlkitocr_v2，已规避 OcrLite 崩溃）")
        except Exception as e:
            log(f"OCR 引擎设置失败（将用默认引擎）: {e}")

        if not launch_app():
            log("❌ 无法启动汽水音乐，脚本终止")
            return

        skip_splash_ad(timeout=5)
        dismiss_popups()

        # 首轮允许找"免"字，能自己进第一个广告
        if wait_for_mian_button(timeout=30, allow_mian=True):
            log("已进入广告，开始核心循环")
        else:
            log("未自动找到入口，请你手动点进一个广告，脚本继续监视")

        total = run_ad_loop()

        log("=" * 60)
        log(f"✅ 脚本运行结束，共成功领取 {total} 次奖励")
        notify(f"汽水音乐安卓版完成，成功 {total} 次")
    except Exception as e:
        log(f"❌ 脚本主流程异常: {e}")
        traceback.print_exc()
    finally:
        log("脚本退出")


# ============== 入口：AScript 工程约定顶层直接执行 ==============
main()
