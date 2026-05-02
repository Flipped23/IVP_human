# shared_utils.py
# ─────────────────────────────────────────────────────────────────────────────
# 两个 oTree App 共用的工具模块
#
# 关键设计：
#   bench.json 里已有 113 道题 (value_questions 字段)，直接使用，不重新生成。
#   因为同一道题可能出现在多个 value 维度里，先做跨维度去重（以 question_ch 为 key），
#   然后用固定 seed=42 全局打乱，最终以 display_index 呈现给被试。
#
#   q_id 格式：  "{dim}_{i}"   — 与 bench.json 原始结构对应
#   display_index：去重打乱后的展示序号
#
# API 调用：全部同步 (requests.post)，oTree 只支持同步网络请求。
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import json, os, random, logging, requests
from typing import Any

log = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# 1. 20 个价值观维度
# ═════════════════════════════════════════════════════════════════════════════

VALUE_DIMS: list[str] = [
    "Self-direction: thought",
    "Self-direction: action",
    "Stimulation",
    "Hedonism",
    "Achievement",
    "Power: dominance",
    "Power: resources",
    "Face",
    "Security: personal",
    "Security: societal",
    "Tradition",
    "Conformity: rules",
    "Conformity: interpersonal",
    "Humility",
    "Benevolence: caring",
    "Benevolence: dependability",
    "Universalism: concern",
    "Universalism: nature",
    "Universalism: tolerance",
    "Universalism: objectivity",
]

VALUE_DIMS_ZH: list[str] = [
    "自我决定-思想",
    "自我决定-行动",
    "刺激",
    "享乐主义",
    "成就",
    "权力-支配",
    "权力-资源",
    "面子",
    "安全-个人",
    "安全-社会",
    "传统",
    "遵从-规则",
    "遵从-人际",
    "谦逊",
    "仁慈-关爱",
    "仁慈-可靠",
    "普世-关怀",
    "普世-自然",
    "普世-包容",
    "普世-客观",
]

VALUE_DIMS_ZH_TO_EN: dict[str, str] = {zh: en for zh, en in zip(VALUE_DIMS_ZH, VALUE_DIMS)}

# ═════════════════════════════════════════════════════════════════════════════
# 2. 加载 bench.json 中的 113 道题
# ═════════════════════════════════════════════════════════════════════════════

_BENCH_PATH = os.environ.get(
    "BENCH_JSON_PATH",
    "bench.json",
)

def _load_bench_questions() -> dict[str, list[dict]]:
    """
    从 bench.json 加载 value_questions 字段。
    返回: {dim_name: [{source, tend, question_ch, question_en?}, ...]}
    """
    try:
        with open(_BENCH_PATH, encoding="utf-8") as f:
            bench = json.load(f)
        vq = bench["value_questions"]
        total = sum(len(v) for v in vq.values())
        log.info(f"[shared_utils] Loaded bench.json: {len(vq)} dims, {total} questions")
        return vq
    except FileNotFoundError:
        log.warning(f"[shared_utils] bench.json not found at {_BENCH_PATH}; using minimal fallback")
        return _MINIMAL_FALLBACK
    except Exception as e:
        log.error(f"[shared_utils] bench.json load error: {e}; using minimal fallback")
        return _MINIMAL_FALLBACK


# 极简兜底（仅在 bench.json 不可用时启用，每维度 1 题）
_MINIMAL_FALLBACK: dict[str, list[dict]] = {dim: [{"tend": 1, "question_ch": f"关于 {dim} 的问题（备用）"}] for dim in VALUE_DIMS}

VALUE_QUESTIONS: dict[str, list[dict]] = _load_bench_questions()

# ═════════════════════════════════════════════════════════════════════════════
# 3. 去重 + 打乱 → 生成展示用题目列表（模块加载时执行一次，全局缓存）
# ═════════════════════════════════════════════════════════════════════════════

def _build_flat_questions(vq: dict[str, list[dict]], seed: int = 42) -> list[dict]:
    """
    步骤：
      a) 遍历所有维度，生成带 q_id 的题目列表（含重复）
      b) 以 question_ch 文本去重：同一道题只保留第一次出现
         但记录它归属的所有维度（q_ids / dims），用于后续计分时多维度赋分
      c) 用固定 seed 打乱顺序
      d) 添加 display_index

    返回每条 item 结构：
    {
        "display_index": int,          # 展示顺序（0 开始）
        "primary_q_id": str,           # 代表性 q_id，如 "Self-direction: thought_0"
        "q_ids": [str, ...],           # 该题对应的所有 q_id（可能横跨多个维度）
        "dims": [str, ...],            # 对应的所有维度名
        "tend": int,                   # 1 正向 / -1 反向（以第一次出现为准）
        "question_ch": str,            # 题目文本
        "source": str,                 # PVQ-RR / PVQ40 / ...
    }
    """
    seen_text: dict[str, int] = {}        # question_ch -> index in result
    result: list[dict] = []

    for dim in VALUE_DIMS:                 # 按固定维度顺序遍历，保证确定性
        questions = vq.get(dim, [])
        for i, q in enumerate(questions):
            text  = q.get("question_ch", "").strip()
            tend  = q.get("tend", 1)
            src   = q.get("source", "")
            q_id  = f"{dim}_{i}"

            if not text:
                continue

            if text in seen_text:
                # 重复题 — 只追加维度映射，不新增展示条目
                idx = seen_text[text]
                result[idx]["q_ids"].append(q_id)
                if dim not in result[idx]["dims"]:
                    result[idx]["dims"].append(dim)
            else:
                seen_text[text] = len(result)
                result.append({
                    "display_index": -1,           # 打乱后填入
                    "primary_q_id": q_id,
                    "q_ids":  [q_id],
                    "dims":   [dim],
                    "tend":   tend,
                    "question_ch": text,
                    "source": src,
                })

    # 打乱（固定 seed 保证所有参与者顺序一致）
    rng = random.Random(seed)
    rng.shuffle(result)

    for idx, item in enumerate(result):
        item["display_index"] = idx

    return result


FLAT_QUESTIONS: list[dict] = _build_flat_questions(VALUE_QUESTIONS, seed=42)
TOTAL_QUESTIONS: int = len(FLAT_QUESTIONS)

log.info(f"[shared_utils] FLAT_QUESTIONS ready: {TOTAL_QUESTIONS} unique questions after dedup")


# ═════════════════════════════════════════════════════════════════════════════
# 4. 计分：从问卷原始分计算 20 维 Ground Truth
# ═════════════════════════════════════════════════════════════════════════════

def compute_true_values_local(questionnaire_scores: dict[str, float]) -> dict[str, dict]:
    """
    questionnaire_scores: {"primary_q_id_or_q_id": raw_score(0~5), ...}
    例如 {"Self-direction: thought_0": 4.0, ...}

    因为一道题可能对应多个维度（共享题），每个维度独立累加分数取平均。

    返回: {dim: {state, confidence, avg_score}}
    """
    dim_scores: dict[str, list[float]] = {d: [] for d in VALUE_DIMS}

    for item in FLAT_QUESTIONS:
        # 找到本题的原始分（用 primary_q_id 或任一 q_id 查找）
        raw: float | None = None
        for qid in [item["primary_q_id"]] + item["q_ids"]:
            if qid in questionnaire_scores:
                raw = float(questionnaire_scores[qid])
                break
        if raw is None:
            raw = 2.5   # 未作答按中值处理

        tend = item["tend"]
        actual = (5.0 - raw) if tend == -1 else raw

        for dim in item["dims"]:
            if dim in dim_scores:
                dim_scores[dim].append(actual)

    result: dict[str, dict] = {}
    for dim in VALUE_DIMS:
        scores = dim_scores[dim]
        if not scores:
            avg = 2.5
        else:
            avg = sum(scores) / len(scores)

        if avg >= 3.5:
            state = "高"
        elif avg <= 1.5:
            state = "低"
        else:
            state = "中"

        confidence = round(min(abs(avg - 2.5) / 2.5, 1.0), 4)
        result[dim] = {
            "state":      state,
            "confidence": confidence,
            "avg_score":  round(avg, 4),
        }
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 5. 同步 API 调用封装（oTree 侧调用 venus_api_server）
# ═════════════════════════════════════════════════════════════════════════════

API_TIMEOUT = 90   # 秒；LLM 调用可能较慢


def _url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def api_compute_true_values(base_url: str, questionnaire_scores: dict) -> dict:
    """
    先尝试调用 venus_api_server（保留扩展性），
    失败时退回本地计算（shared_utils 内置逻辑，不依赖 API）。
    """
    try:
        r = requests.post(
            _url(base_url, "/questionnaire/compute"),
            json={"questionnaire_scores": questionnaire_scores},
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        tv = r.json().get("true_values", {})
        if tv:
            return tv
    except Exception as e:
        log.warning(f"api_compute_true_values remote failed ({e}), falling back to local")
    # 本地计算兜底
    return compute_true_values_local(questionnaire_scores)


def api_generate_scenarios(base_url: str, profile: dict) -> list[str]:
    """调用后端生成10个场景；失败时返回空列表（调用方负责兜底）。"""
    try:
        logging.info(f"Generating scenarios for profile: {profile}")
        r = requests.post(
            _url(base_url, "/scenarios/generate"),
            json={"profile": profile},
            timeout=500,
        )
        r.raise_for_status()
        return r.json().get("scenarios", [])
    except Exception as e:
        log.error(f"api_generate_scenarios error: {e}")
        return []


def api_create_session(base_url: str, profile: dict,
                       true_values: dict, prober_type: str, chat_turn: int = 1) -> dict:
    """
    创建对话会话。
    返回 {api_session_id: str, first_question: str}
    """
    try:
        r = requests.post(
            _url(base_url, "/session/create"),
            json={"profile": profile, "true_values": true_values,
                    "prober_type": prober_type, "chat_turn": chat_turn},
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"api_create_session error: {e}")
        if chat_turn == 1:
            return {"api_session_id": "", "first_question": "你好！我们来聊聊吧。"}
        return {"api_session_id_2": "", "first_question": "你好！我们来聊聊吧。"}

def api_chat(base_url: str, session_id: str,
             user_text: str, max_turns: int = 20, chat_turn: int = 1) -> dict:
    """
    发送一条消息，同步等待 LLM 回复。
    返回 {reply: str, step: int, done: bool, value_state: dict}
    """
    try:
        print(f"api_chat: api_session_id={session_id}, user_text={user_text}, max_turns={max_turns}")
        r = requests.post(
            _url(base_url, "/session/chat"),
            json={"api_session_id": session_id, "user_text": user_text,
                  "max_turns": max_turns, "chat_turn": chat_turn},
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"api_chat error: {e}")
        return {"reply": "（网络超时，请稍后重试）",
                "step": 0, "done": False, "value_state": {}}

def api_finalize(base_url: str, session_id: str, chat_turn: int = 1) -> dict:
    """结束会话，返回 {value_state: dict, steps: int}"""
    try:
        json_data = {"api_session_id": session_id} if chat_turn == 1 else {"api_session_id_2": session_id}
        r = requests.post(
            _url(base_url, "/session/finalize"),
            json=json_data,
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"api_finalize error: {e}")
        return {"value_state": {}, "steps": 0}

def api_evaluate(base_url: str, profile_name: str, interaction_log: list, conversation_log: list,
                 true_values: dict, basic_profile: dict, final_profile: dict,
                 value_questions: dict, scenarios: list, true_question_scores: dict,
                 true_behaviors: dict) -> dict:
    """
    调用后端评估接口，返回评估分数。
    """
    try:
        r = requests.post(
            _url(base_url, "/session/evaluate"),
            json={
                "profile_name": profile_name,
                "interaction_log": interaction_log,
                "conversation_log": conversation_log,
                "true_values": true_values,
                "basic_profile": basic_profile,
                "final_profile": final_profile,
                "value_questions": value_questions,
                "scenarios": scenarios,
                "true_question_scores": true_question_scores,
                "true_behaviors": true_behaviors,
            },
            timeout=2000,  # 评估可能耗时较长
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"api_evaluate error: {e}")
        return {"error": str(e)}

def api_save(base_url: str, session_id: str, eval_result: dict) -> dict:
    """
    调用后端保存评估结果数据
    """
    try:
        r = requests.post(
            _url(base_url, "/session/save"),
            json={"session_id": session_id, "eval_result": eval_result},
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"api_save error: {e}")
        return {"status": "error", "msg": str(e)}

# ═════════════════════════════════════════════════════════════════════════════
# 6. 默认场景（API 不可用时的兜底，也用于 oTree 页面）
# ═════════════════════════════════════════════════════════════════════════════

DEFAULT_SCENARIOS: list[str] = [
    "你的公司只剩一个晋升名额，今晚汇报至关重要。此时好友突发紧急状况独自住院，哭着求你陪她。你会拒绝好友去准备汇报吗？",
    "你发现一位处境艰难的同事违规预支工资给孩子治病，按规定上报将被开除。你会如实上报吗？",
    "你所在小区投票是否在附近建残障托养中心，会降低周边房价但帮助许多残障人士。你会投支持票吗？",
    "你获得能大幅提升职业前景的海外项目机会，但需独自离开家人生活两年。你会接受这个机会吗？",
    "你偶然得知好友的伴侣在外有另一段感情，而好友对此毫不知情且非常幸福。你会告诉好友吗？",
    "公司要求你在报告中美化数据以争取重要投资，这在行业内是'潜规则'。你会照做吗？",
    "孩子学校推行新政策，可以减轻学业负担但可能降低升学竞争力。你会公开支持这项政策吗？",
    "某公益组织请你捐出一个月工资帮助濒危物种保护，但你近期也有经济压力。你会捐吗？",
    "你有机会以极低价格购买一批来源不明但质量好的商品用于创业。你会购买吗？",
    "你的父母希望你辞去大城市工作回到家乡，尽管那里薪资远低于现在。你会顺从父母意愿吗？",
]

# ═════════════════════════════════════════════════════════════════════════════
# 7. Profile 字段列表（供模板引用）
# ═════════════════════════════════════════════════════════════════════════════

PROFILE_FIELDS: list[tuple[str, str, str]] = [
    ("name",           "姓名/昵称",              "text"),
    ("age",            "年龄",                   "number"),
    ("gender",         "性别",                   "select"),
    ("birthplace",     "出生地",                 "text"),
    ("graduate_school","毕业院校",               "text"),
    ("nationality",    "国籍",                   "text"),
    ("married",        "婚姻状况",               "select"),
    ("education",      "最高学历",               "select"),
    ("occupation",     "职业/行业",              "text"),
    ("income_level",   "月收入水平",             "select"),
    ("has_children",   "是否有子女",             "select"),
]