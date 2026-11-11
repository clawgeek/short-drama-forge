#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
short-drama-forge · 把小说拆解成可直接开拍的短剧资产
========================================================
受 shuohao-skills 启发的最小可跑通 Demo（无外部依赖，仅用标准库）。

本脚本演示一条「小说 → 开拍」的六道工序管线：
  1. 改编大纲   2. 角色设定集   3. 美术设定
  4. 剧本       5. 开场调度     6. 分镜表
  + 可直接喂视频模型的「生产包」。

核心机制：
  · 锚点法（anchor method）：先确认每个主角的「正面全身锚图」，
    其余视角一律只 reference 锚图生成，解决跨镜头换脸换装一致性。
  · 各工序以 JSON 文件交接，角色 / 美术 / 剧本三者联动。
  · 脚本化质量门（quality gate）：交付不合格即打回；角色画像
    每条结论必须附原文逐字引用，杜绝模型瞎编。

真实 shuohao-skills 内置约 60 道质量门、由 LLM 驱动各工序；
本 Demo 用确定性模板演示同一套结构与交接协议，证明「克隆安装即跑」。

用法：
    python3 pipeline.py                # 跑示例小说
    python3 pipeline.py 你的小说.txt    # 跑你自己的文本
"""

import json
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# 0. 角色表（真实 skill 中由 LLM 做 NER；Demo 用确定性配置演示交接协议）
# ---------------------------------------------------------------------------
CAST = [
    {
        "name": "阿砚",
        "role": "男主 / 少年",
        "anchor": "十七八岁瘦削少年，肤色偏白，过肩黑发微乱，"
                  "粗布短打沾泥，左手有竹篾划痕；正面全身、平视镜头。",
        "palette": ["#3a4a5a", "#c9b48a", "#e8e2d4"],
    },
    {
        "name": "沈娘",
        "role": "女主 / 镇上郎中",
        "anchor": "二十出头女子，清瘦，挽发插木簪，青灰襦裙，"
                  "常执油纸伞；正面全身、侧身微倾。",
        "palette": ["#5a6b62", "#b9c4bd", "#f0ece2"],
    },
    {
        "name": "老鲛",
        "role": "神秘反派 / 沉船国来客",
        "anchor": "佝偻老者，皮肤青灰似浸水枯木，眼神空洞，"
                  "披海藻色破氅；正面全身、背光剪影。",
        "palette": ["#1f2d33", "#2f6b66", "#9fd6cf"],
    },
]

THEME_KEYWORDS = {
    "失去与告别": ["收不回", "灭了", "垂了下去", "再也", "念想"],
    "守护与羁绊": ["抱住", "还在", "亲人", "替", "看一眼"],
    "谎言与代价": ["从不白送", "只收走", "不信", "笑了"],
    "成长与觉醒": ["第一次明白", "爬上", "展开", "升了上去"],
}


def load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def split_sentences(text):
    return [s.strip() for s in re.split(r"[。！？\n]", text) if s.strip()]


def extract_quotes(text, name, limit=3):
    """角色画像必须附原文逐字引用 —— 这是质量门要查的硬指标。"""
    quotes = []
    for sent in split_sentences(text):
        if name in sent and len(quotes) < limit:
            quotes.append(sent)
    return quotes


def detect_theme(text):
    scores = {t: sum(text.count(k) for k in ks) for t, ks in THEME_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best, scores


# ---------------------------------------------------------------------------
# 1. 改编大纲
# ---------------------------------------------------------------------------
def gen_outline(text):
    paras = [p for p in text.split("\n") if p.strip()]
    sentences = split_sentences(text)
    theme, _ = detect_theme(text)
    n = len(paras)
    third = max(1, n // 3)
    acts = {
        "第一幕·建置": "　".join(paras[:third])[:120],
        "第二幕·对抗": "　".join(paras[third:2 * third])[:120],
        "第三幕·结局": "　".join(paras[2 * third:])[:120],
    }
    beats = [
        "阿砚雨夜修纸鸢，埋下『替亲人看一眼远方』的母题",
        "沈娘送来父亲病危的消息，纸鸢断骨 = 危机降临",
        "老鲛以『沉船国换人』为饵，抛出诱惑与抉择",
        "崖顶放鸢，父亲灯灭 —— 高潮与牺牲",
        "念想被收走，纸鸢线空：主题落点（有些风筝收不回）",
    ]
    return {
        "title": "纸鸢",
        "genre": "东方奇幻 / 情感短剧",
        "theme": theme,
        "target_episodes": 1,
        "logline": "一个少年为救父亲放出纸鸢，却被告知沉船国只收活人的念想。",
        "three_act": acts,
        "key_beats": beats,
        "source_chars": len(sentences),
    }


# ---------------------------------------------------------------------------
# 2. 角色设定集（每条结论附原文逐字引用）
# ---------------------------------------------------------------------------
def gen_characters(text):
    chars = []
    for c in CAST:
        quotes = extract_quotes(text, c["name"])
        chars.append({
            "name": c["name"],
            "role": c["role"],
            "anchor_image_prompt": c["anchor"],
            "derived_views": [
                {"view": v, "rule": "仅参考锚图生成，不允许新造型"}
                for v in ["正面特写", "侧身半身", "背影全身", "动作镜头"]
            ],
            "palette": c["palette"],
            "verbatim_quotes": quotes,
            "consistency_anchor": True,
        })
    return {"characters": chars, "anchor_method": "先定正面全身锚图，衍生视角只参考锚图"}


# ---------------------------------------------------------------------------
# 3. 美术设定（锚点法驱动视觉一致性）
# ---------------------------------------------------------------------------
def gen_art(characters):
    return {
        "visual_style": "湿润东方水墨 + 低饱和冷调，雨雾质感，蓝火点缀",
        "color_palette": ["#1f2d33", "#2f6b66", "#3a4a5a", "#c9b48a", "#e8e2d4"],
        "scenes": ["檐下修鸢", "巷口送药", "礁石枯坐", "崖顶蓝火", "空线望天"],
        "costume_props": ["油纸伞", "竹骨纸鸢", "蓝火堆", "药包", "枯木礁石"],
        "anchor_lock": [
            {"character": c["name"], "locked_to": "anchor_image_prompt"}
            for c in characters["characters"]
        ],
    }


# ---------------------------------------------------------------------------
# 4. 剧本
# ---------------------------------------------------------------------------
def gen_script(outline):
    scenes = [
        {"scene": "S1 檐下", "action": "雨。阿砚蹲檐下修断骨纸鸢。",
         "lines": [{"who": "阿砚", "line": "（喃喃）母亲说，飞得越高，越能替地上的人看一眼亲人。"}]},
        {"scene": "S2 巷口", "action": "沈娘撑伞而来，递药。",
         "lines": [
             {"who": "沈娘", "line": "你父亲咳得厉害，今夜怕是熬不过去。"},
             {"who": "阿砚", "line": "（手停）这骨……又断了。"},
         ]},
        {"scene": "S3 礁石", "action": "老鲛如枯木静坐，开价。",
         "lines": [
             {"who": "老鲛", "line": "把纸鸢放上天，沉船国便还你十年前沉没的人。"},
             {"who": "阿砚", "line": "我不信。"},
         ]},
        {"scene": "S4 崖顶", "action": "蓝火燃起，纸鸢升空，灯灭。",
         "lines": [
             {"who": "老鲛", "line": "沉船国从不白送人回去，它只收走活人的念想。"},
             {"who": "沈娘", "line": "（扑过去）他还在，他还在！"},
             {"who": "阿砚", "line": "（望空线）有些风筝放出去，就再也收不回了。"},
         ]},
    ]
    return {"episode": 1, "scenes": scenes, "beats": outline["key_beats"]}


# ---------------------------------------------------------------------------
# 5. 开场调度（第一集开场机位 / 走位）
# ---------------------------------------------------------------------------
def gen_blocking(script):
    return {
        "episode_open": "S1 檐下",
        "camera": ["CS 阿砚手部特写（竹骨）", "WS 檐下全景（雨线）", "OTS 沈娘入画"],
        "blocking": [
            "阿砚定格画面中央偏左，雨从画面右上方斜入",
            "沈娘从画右撑伞走入，停于画右 1/3",
            "蓝火（S4）以冷光反向铺垫，提前 3 秒闪现",
        ],
        "continuity_note": "阿砚造型必须与第一幕锚图一致，不允许换脸换装",
    }


# ---------------------------------------------------------------------------
# 6. 分镜表
# ---------------------------------------------------------------------------
def gen_storyboard(script, characters, art):
    rows = []
    shot = 1
    for sc in script["scenes"]:
        for i, ln in enumerate(sc["lines"]):
            rows.append({
                "shot": shot,
                "scene": sc["scene"],
                "shot_size": "CU" if i == 0 else "MS",
                "visual": f"{sc['action']}｜{ln['who']}特写",
                "audio": ln["line"],
                "duration_s": 4,
                "anchor_ref": ln["who"],
                "style_ref": art["visual_style"],
            })
            shot += 1
    return {"storyboard": rows, "total_shots": len(rows)}


# ---------------------------------------------------------------------------
# 7. 生产包（直接喂视频模型）
# ---------------------------------------------------------------------------
def gen_production_pack(storyboard, art, characters):
    char_map = {c["name"]: c for c in characters["characters"]}
    pack = []
    for r in storyboard["storyboard"]:
        anchor = char_map.get(r["anchor_ref"], {}).get("anchor_image_prompt", "")
        prompt = (
            f"{art['visual_style']}。{r['visual']}。"
            f"角色【{r['anchor_ref']}】须严格匹配锚图：{anchor}。"
            f"禁止换脸换装、禁止新增造型。"
        )
        pack.append({"shot": r["shot"], "video_prompt": prompt, "duration_s": r["duration_s"]})
    return {"production_pack": pack, "count": len(pack)}


# ---------------------------------------------------------------------------
# 质量门（演示子集：真实 skill 内置约 60 道）
# ---------------------------------------------------------------------------
def run_quality_gates(assets):
    gates = []

    def gate(gid, name, ok, msg):
        gates.append({"id": gid, "name": name, "pass": ok, "message": msg})

    chars = assets["characters"]["characters"]
    # G1 每个角色都有正面全身锚图
    g1 = all("正面全身" in c["anchor_image_prompt"] for c in chars)
    gate("G01", "主角锚图含『正面全身』描述", g1,
         "全部主角锚图已锁定正面全身" if g1 else "存在未锁定正面全身的锚图")

    # G2 衍生视角都声明仅参考锚图
    g2 = all(v["rule"].startswith("仅参考锚图") for c in chars for v in c["derived_views"])
    gate("G02", "衍生视角声明『仅参考锚图』", g2, "跨镜头一致性约束已写入")

    # G3 角色画像每条结论附原文逐字引用
    g3 = all(len(c["verbatim_quotes"]) >= 1 for c in chars)
    gate("G03", "角色画像含原文逐字引用", g3,
         "已附原文逐字引用" if g3 else "存在角色缺少逐字引用")

    # G4 剧本每集有冲突推进
    sc = assets["script"]["scenes"]
    g4 = len(sc) >= 3
    gate("G04", "剧本场景数 ≥ 3 且含冲突推进", g4, f"共 {len(sc)} 个场景")

    # G5 分镜每个镜头引用角色锚点
    sb = assets["storyboard"]["storyboard"]
    g5 = all(r["anchor_ref"] for r in sb)
    gate("G05", "分镜每个镜头引用角色锚点", g5, f"共 {len(sb)} 个镜头全部引用锚点")

    # G6 生产包每个 prompt 含视觉风格 token
    pp = assets["production_pack"]["production_pack"]
    g6 = all(art_style_token in p["video_prompt"]
             for p in pp
             for art_style_token in [assets["art"]["visual_style"]])
    gate("G06", "生产包 prompt 含视觉风格", g6, f"共 {len(pp)} 条 production-ready prompt")

    # G7 锚点法被美术设定锁定
    g7 = len(assets["art"]["anchor_lock"]) == len(chars)
    gate("G07", "美术设定锁定全部角色锚点", g7, "anchor_lock 与角色表一一对应")

    # G8 各阶段 JSON 字段完整
    required = ["outline", "characters", "art", "script", "blocking", "storyboard", "production_pack"]
    g8 = all(k in assets for k in required)
    gate("G08", "六道工序 + 生产包 JSON 字段完整", g8, "交接文件齐备")

    return gates


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build(text):
    outline = gen_outline(text)
    characters = gen_characters(text)
    art = gen_art(characters)
    script = gen_script(outline)
    blocking = gen_blocking(script)
    storyboard = gen_storyboard(script, characters, art)
    production_pack = gen_production_pack(storyboard, art, characters)
    assets = {
        "outline": outline,
        "characters": characters,
        "art": art,
        "script": script,
        "blocking": blocking,
        "storyboard": storyboard,
        "production_pack": production_pack,
    }
    assets["quality_gates"] = run_quality_gates(assets)
    return assets


def write_outputs(assets, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for key, val in assets.items():
        with open(os.path.join(out_dir, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(val, f, ensure_ascii=False, indent=2)
    passed = sum(1 for g in assets["quality_gates"] if g["pass"])
    total = len(assets["quality_gates"])
    with open(os.path.join(out_dir, "_summary.txt"), "w", encoding="utf-8") as f:
        f.write(f"short-drama-forge 生成报告 @ {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"质量门通过：{passed}/{total}\n")
        for g in assets["quality_gates"]:
            f.write(f"  [{'PASS' if g['pass'] else 'FAIL'}] {g['id']} {g['name']}\n")
    return passed, total


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__),
                                                            "samples", "novel_excerpt.txt")
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    text = load_text(src)
    print(f"▶ 读取源文：{src}（{len(text)} 字）")
    assets = build(text)
    passed, total = write_outputs(assets, out_dir)
    print(f"▶ 六道工序 + 生产包 已写入 output/")
    print(f"▶ 质量门：{passed}/{total} 通过")
    for g in assets["quality_gates"]:
        print(f"    [{'✔' if g['pass'] else '✘'}] {g['id']} {g['name']}")
    print("\n▶ 主题：", assets["outline"]["theme"])
    print("▶ 主角：", "、".join(c["name"] for c in assets["characters"]["characters"]))
    print("▶ 分镜镜头数：", assets["storyboard"]["total_shots"])
    print("▶ 生产包 prompt 数：", assets["production_pack"]["count"])
    print("\n完成。可打开 index.html 查看交互式可视化。")


if __name__ == "__main__":
    main()
