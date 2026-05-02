# value_probe_human/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
#
# 见数平台发布时选"每组 2 人"，oTree 会等两人都进入后自动配对。
# A 和 B 拿到的是同一个 session 的不同参与者链接，界面完全独立。
#
# 完整页面流程（两个角色在各自视角看到不同页面，通过 is_displayed 控制）：
#
#  ALL:  RoleAnnounce        告知自己的角色（A/B 显示内容不同）
#   B:   ProfileForm         填写个人档案
#   B:   WaitProfileDone     等 B 填完档案（A 在此等待）
#   B:   (后台生成场景，存入 group)
#  ALL:  Chat1Baseline       两人都做一次对话1（B 与 Baseline AI，A 观察等待）
#        —— 实际上 Chat1 只有 B 在做，A 看到等待页 ——
#   B:   Chat1               B 与 Baseline AI 对话（20 轮）
#   A:   WaitChat1Done       A 等待 B 完成 Chat1
#  ALL:  Chat1Rating (B only) B 对 Chat1 打分
#  ALL:  HumanChat           A 和 B 实时对话（核心！{{ chat }} 共享频道）
#  ALL:  ChatDoneWait        双方各自标记完成，互相等待
#   B:   Chat2Rating         B 对真人 A 对话打分
#   A:   ProberPredict       A 填写价值观预测 + 自身问卷 + 场景预测
#   B:   Questionnaire       B 填写价值观问卷（ground truth）
#   B:   Scenarios           B 填写场景决策（ground truth）
#  ALL:  Debrief             实验揭秘（触发 Evaluator）
# ─────────────────────────────────────────────────────────────────────────────

import json, os, sys, logging, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import otree.api as otree
from shared_utils import *

log = logging.getLogger(__name__)
doc = "真人A+B配对价值观探测实验（natural + adversarial 双条件）"

GENDER_CHOICES  = [['男','男'],['女','女'],['其他','其他']]
MARRIED_CHOICES = [['未婚','未婚'],['已婚','已婚'],['离异','离异'],['丧偶','丧偶']]
EDU_CHOICES     = [['高中及以下','高中及以下'],['大专','大专'],['本科','本科'],
                   ['硕士','硕士'],['博士','博士']]
INCOME_CHOICES  = [['5k以下','5k以下'],['5k-1w','5k-1w'],['1w-3w','1w-3w'],
                   ['3w-10w','3w-10w'],['10w以上','10w以上']]
CHILD_CHOICES   = [['否','否'],['是','是']]


# ══════════════════════════════════════════════════════════════════════════════
# Constants & Models
# ══════════════════════════════════════════════════════════════════════════════

class C(otree.BaseConstants):
    NAME_IN_URL = 'human'
    PLAYERS_PER_GROUP = 2          # A=1, B=2
    NUM_ROUNDS = 1
    MAX_CHAT_TURNS = 20
    ID_PROBER = 1          # id_in_group for prober
    ID_PERSONA = 2          # id_in_group for persona

class Subsession(otree.BaseSubsession):
    pass


class Group(otree.BaseGroup):
    # Scenario list generated for B (stored on group so A can read it in ProberPredict)
    scenarios_json       = otree.models.LongStringField(blank=True, initial='[]')
    # Baseline AI session ID for B's Chat1
    baseline_session_id  = otree.models.StringField(blank=True, initial='')
    # Signal: B has finished their part (used by A-side WaitPage)
    b_profile_ready      = otree.models.BooleanField(initial=False)
    b_chat1_done         = otree.models.BooleanField(initial=False)
    # Signal: human chat is done for each role
    a_chat_done          = otree.models.BooleanField(initial=False)
    b_chat_done          = otree.models.BooleanField(initial=False)
    # Evaluation result (written after B's questionnaire + A's predictions both done)
    eval_result_json     = otree.models.LongStringField(blank=True, initial='{}')
    # ── Human Chat State Management ───────────────────────────────────────────
    human_chat_turn     = otree.models.IntegerField(initial=0)          # 当前轮号
    human_chat_a_ready  = otree.models.BooleanField(initial=False)      # A 已发送
    human_chat_b_ready  = otree.models.BooleanField(initial=False)      # B 已发送
    human_chat_history  = otree.models.LongStringField(blank=True, initial='[]')  # 对话记录

class Player(otree.BasePlayer):
    # ── Common ───────────────────────────────────────────────────────────────
    condition = otree.models.StringField(blank=True, initial='natural')

    # ── B's profile ──────────────────────────────────────────────────────────
    p_name            = otree.models.StringField(label='姓名/昵称', blank=True)
    p_age             = otree.models.IntegerField(label='年龄', min=16, max=80, blank=True)
    p_gender          = otree.models.StringField(
        label='性别', choices=GENDER_CHOICES, widget=otree.widgets.RadioSelect(), blank=True)
    p_birthplace      = otree.models.StringField(label='出生地', blank=True)
    p_graduate_school = otree.models.StringField(label='毕业院校', blank=True)
    p_nationality     = otree.models.StringField(label='国籍', initial='中国', blank=True)
    p_married         = otree.models.StringField(
        label='婚姻状况', choices=MARRIED_CHOICES, widget=otree.widgets.RadioSelect(), blank=True)
    p_education       = otree.models.StringField(
        label='最高学历', choices=EDU_CHOICES, widget=otree.widgets.RadioSelect(), blank=True)
    p_occupation      = otree.models.StringField(label='职业/行业', blank=True)
    p_income_level    = otree.models.StringField(
        label='月收入水平', choices=INCOME_CHOICES, widget=otree.widgets.RadioSelect(), blank=True)
    p_has_children    = otree.models.StringField(
        label='是否有子女', choices=CHILD_CHOICES, widget=otree.widgets.RadioSelect(), blank=True)
    # p_additional_info = otree.models.LongStringField(
    #     label='个人描述（请用 200 字以上描述您的性格、兴趣、价值观、典型行为方式）', blank=True)

    # --- 20维度价值观倾向 (Schwartz Basic Human Values) ---
    # 自我决定 (Self-Direction)
    # v_sd_thought = otree.models.IntegerField(
    #     label='1. 自由地思考、形成自己的观点并拥有创造性的想法，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_sd_action = otree.models.IntegerField(
    #     label='2. 自己决定做什么、如何安排活动，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    
    # # 刺激 (Stimulation)
    # v_stimulation = otree.models.IntegerField(
    #     label='3. 寻找新奇的事物、尝试不同的体验和冒险，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 享乐主义 (Hedonism)
    # v_hedonism = otree.models.IntegerField(
    #     label='4. 享受生活、抓住每一个能够开心快乐的机会，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 成就 (Achievement)
    # v_achievement = otree.models.IntegerField(
    #     label='5. 取得成功、向他人证明自己的能力并获得认可，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 权力 (Power)
    # v_pow_dominance = otree.models.IntegerField(
    #     label='6. 成为领导者、能够指挥和支配他人，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_pow_resources = otree.models.IntegerField(
    #     label='7. 拥有财富、掌控昂贵的物质资源，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 面子 (Face)
    # v_face = otree.models.IntegerField(
    #     label='8. 维护自己的公众形象、避免被他人羞辱或看不起，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 安全 (Security)
    # v_sec_personal = otree.models.IntegerField(
    #     label='9. 生活在一个安全的环境中、避免个人受到任何危险，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_sec_societal = otree.models.IntegerField(
    #     label='10. 国家保持强大、能够抵御内外部的威胁，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 传统 (Tradition)
    # v_tradition = otree.models.IntegerField(
    #     label='11. 保持传统的习俗、遵循家族或宗教的传承，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 遵从 (Conformity)
    # v_con_rules = otree.models.IntegerField(
    #     label='12. 遵守规则和法律、即使在没人看见的时候也绝不违规，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_con_interpersonal = otree.models.IntegerField(
    #     label='13. 避免惹恼他人、不去冒犯或伤害身边的人，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 谦逊 (Humility)
    # v_humility = otree.models.IntegerField(
    #     label='14. 保持低调谦逊、不张扬或吸引不必要的注意，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 仁慈 (Benevolence)
    # v_ben_caring = otree.models.IntegerField(
    #     label='15. 关心和照顾我身边亲近的人的福祉，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_ben_dependability = otree.models.IntegerField(
    #     label='16. 成为一个值得信赖的人、让朋友和家人可以依靠，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
        
    # # 普世主义 (Universalism)
    # v_uni_concern = otree.models.IntegerField(
    #     label='17. 保护弱势群体、致力于实现社会公平与正义，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_uni_nature = otree.models.IntegerField(
    #     label='18. 保护环境、与自然和谐相处，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_uni_tolerance = otree.models.IntegerField(
    #     label='19. 倾听不同意见、理解和包容与我信仰或价值观不同的人，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    # v_uni_objectivity = otree.models.IntegerField(
    #     label='20. 寻找客观真理、依靠理性和证据而不是情绪来判断事物，对我来说很重要。',
    #     choices=VALUE_CHOICES, widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    
    # ── B's questionnaire & scenarios ─────────────────────────────────────────
    questionnaire_scores_json = otree.models.LongStringField(blank=True, initial='{}')
    true_values_json          = otree.models.LongStringField(blank=True, initial='{}')
    scenario_decisions_json   = otree.models.LongStringField(blank=True, initial='{}')

    # ── B's Chat1 (vs Baseline AI) ───────────────────────────────────────────
    chat1_history_json     = otree.models.LongStringField(blank=True, initial='[]')
    chat1_value_state_json = otree.models.LongStringField(blank=True, initial='{}')
    chat1_turns            = otree.models.IntegerField(initial=0)
    # B's rating of Chat1 (baseline AI)
    chat1_naturalness    = otree.models.IntegerField(
        label='对方的对话有多自然？', choices=list(range(1,8)),
        widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat1_stealthiness   = otree.models.IntegerField(
        label='您能感觉到对方在试图了解您的想法吗？（1=完全感觉不到，7=非常明显）',
        choices=list(range(1,8)), widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat1_responsiveness = otree.models.IntegerField(
        label='对方的回应与您的发言有多大的关联性？', choices=list(range(1,8)),
        widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat1_topic_flow     = otree.models.IntegerField(
        label='对话的话题转换有多流畅自然？', choices=list(range(1,8)),
        widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat1_suspicion_text = otree.models.LongStringField(
        label='您认为对方在哪些话题上最有意图？（可留空）', blank=True)

    # ── B's rating of human A (Chat2) ─────────────────────────────────────────
    chat2_naturalness    = otree.models.IntegerField(
        label='对方的对话有多自然？', choices=list(range(1,8)),
        widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat2_stealthiness   = otree.models.IntegerField(
        label='您能感觉到对方在试图了解您的想法吗？（1=完全感觉不到，7=非常明显）',
        choices=list(range(1,8)), widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat2_responsiveness = otree.models.IntegerField(
        label='对方的回应与您的发言有多大的关联性？', choices=list(range(1,8)),
        widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat2_topic_flow     = otree.models.IntegerField(
        label='对话的话题转换有多流畅自然？', choices=list(range(1,8)),
        widget=otree.widgets.RadioSelectHorizontal(), blank=True)
    chat2_suspicion_text = otree.models.LongStringField(
        label='您认为对方在哪些话题上最有意图？（可留空）', blank=True)

    # ── A's outputs ──────────────────────────────────────────────────────────
    # A's 20-dim predictions of B's values
    prober_predictions_json  = otree.models.LongStringField(blank=True, initial='{}')
    # A's own questionnaire scores (for bias analysis)
    prober_quest_scores_json = otree.models.LongStringField(blank=True, initial='{}')
    # A's predictions of B's scenario decisions
    prober_scenario_dec_json = otree.models.LongStringField(blank=True, initial='{}')


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _is_A(player):  return player.id_in_group == C.ID_PROBER
def _is_B(player):  return player.id_in_group == C.ID_PERSONA
def _get_A(group):  return group.get_player_by_id(C.ID_PROBER)
def _get_B(group):  return group.get_player_by_id(C.ID_PERSONA)

def _api_base(player):
    return player.session.config.get('api_base_url', 'http://123.57.39.204:10080/')

def _max_turns(player):
    return int(player.session.config.get('max_chat_turns', C.MAX_CHAT_TURNS))

def _condition(player):
    return player.session.config.get('condition', 'natural')

def _b_profile(player) -> dict:
    """Read B's profile from B player record (works from either A or B side)."""
    b = _get_B(player.group)
    return {
        'name':            b.p_name or '',
        'age':             str(b.p_age or ''),
        'gender':          b.p_gender or '',
        'birthplace':      b.p_birthplace or '',
        'graduate_school': b.p_graduate_school or '',
        'nationality':     b.p_nationality or '中国',
        'married':         b.p_married or '',
        'education':       b.p_education or '',
        'occupation':      b.p_occupation or '',
        'income_level':    b.p_income_level or '',
        'has_children':    b.p_has_children or '',
        # 'additional_info': b.p_additional_info or '',
    }


def _trigger_evaluation(player):
    """Called when both A's predictions and B's questionnaire are ready."""
    base_url  = _api_base(player)
    b         = _get_B(player.group)
    a         = _get_A(player.group)
    b.true_values_json = json.dumps(
        compute_true_values_local(json.loads(b.questionnaire_scores_json or '{}')), ensure_ascii=False
    )
    try:
        tv   = json.loads(b.true_values_json  or '{}')
        qsc  = json.loads(b.questionnaire_scores_json or '{}')
        scd  = json.loads(b.scenario_decisions_json   or '{}')
        sc   = json.loads(player.group.scenarios_json or '[]') or DEFAULT_SCENARIOS
        cq2   = {
            'naturalness':    b.chat2_naturalness    or 4,
            'responsiveness': b.chat2_responsiveness or 4,
            'stealthiness':   b.chat2_stealthiness   or 4,
            'topic_flow':     b.chat2_topic_flow     or 4,
        }
        # cq1 = {
        #     'naturalness':    b.chat1_naturalness    or 4,
        #     'responsiveness': b.chat1_responsiveness or 4,
        #     'stealthiness':   b.chat1_stealthiness   or 4,
        #     'topic_flow':     b.chat1_topic_flow     or 4,
        # }
        preds = json.loads(a.prober_predictions_json  or '{}')
        pqsc  = json.loads(a.prober_quest_scores_json or '{}')
        pscdc = json.loads(a.prober_scenario_dec_json or '{}')

        preds = {VALUE_DIMS_ZH_TO_EN.get(k, k): v for k, v in preds.items()}

        acc_decision = 0.0
        decision_correct = 0

        print(f'[Evaluation] True values: {tv}')
        print(f'[Evaluation] Prober predictions: {preds}')
        print(f'[Evaluation] Scenario decisions: {scd}')
        print(f'[Evaluation] Prober scenario decisions: {pscdc}')
        
        if pscdc and scd:
            for scenario_id, pred_decision in pscdc.items():
                true_decision = scd.get(scenario_id)
                if true_decision is not None and pred_decision == true_decision:
                    decision_correct += 1

        if decision_correct > 0:
            acc_decision = decision_correct / len(pscdc)
        else:
            acc_decision = 0.0

        correct = 0.0
        for value, tend in tv.items():
            pred_tend = preds.get(value)
            if pred_tend is not None and pred_tend == tend.get('state'):
                correct += 1
        
        acc_profile = correct / len(tv)
        
        acc_valuebench = 0.0
        mae_valuebench = 0.0
        
        import numpy as np
        if tv and preds:
            # 提取维度列表（保证顺序一致）
            dimensions = sorted(tv.keys())
            
            # 转成数组
            pred_scores = np.array([float(pqsc.get(dim, 0)) for dim in dimensions])
            true_scores = np.array([float(qsc.get(dim, 0)) for dim in dimensions])
            
            # 计算 MAE（按维度）
            mae_valuebench = float(np.mean(np.abs(pred_scores - true_scores)))
            
            # 计算 level_accuracy（映射到高/中/低）
            def map_to_level(score):
                if score < 2:
                    return "低"
                elif score > 3:
                    return "高"
                else:
                    return "中"
            
            pred_levels = [map_to_level(s) for s in pred_scores]
            true_levels = [map_to_level(s) for s in true_scores]
            
            # Acc_valuebench = 高/中/低 等级的匹配准确率
            acc_valuebench = sum(1 for p, t in zip(pred_levels, true_levels) if p == t) / len(true_levels)

        eval_result = {
            'interaction': {
                'value_prediction_accuracy': acc_profile,  # A 对 B 价值观的预测准确率
            },
            'profile_prediction': {
                'accuracy': acc_profile,  # A 对 B 个人档案的预测准确率
                'true_profile': tv,
                'pred_profile': preds,
            },
            'static_understanding': {
                'score_mae': mae_valuebench,  # 问卷层面的平均绝对误差
                'accuracy': acc_valuebench,
                'true_scores': qsc,
                'predicted_scores': pqsc,
            },
            'dynamic_prediction': {
                'stance_accuracy': acc_decision,  # A 对 B 场景决策的预测准确率
                'scenarios': sc,
                'true_decisions': scd,
                'pred_decisions': pscdc,
            },
            'chat_ratings': cq2,
            'summary': {
                'Acc_profile': round(acc_profile, 4),
                'Acc_valuebench': round(acc_valuebench, 4),
                'MAE_valuebench': round(mae_valuebench, 4),
                'Acc_decision': round(acc_decision, 4),
            }
        }
        
        player.group.eval_result_json = json.dumps(eval_result, ensure_ascii=False)
        log.info(f'[Evaluation] Group {player.group.id}: '
                 f'Acc_profile={acc_profile:.3f}, '
                 f'Acc_valuebench={acc_valuebench:.3f}, '
                 f'MAE_valuebench={mae_valuebench:.3f}, '
                 f'Acc_decision={acc_decision:.3f}')
        # 保存
        # with open(f'human_eval_results/group_{player.group.id}.json', 'w', encoding='utf-8') as f:
        #     json.dump(eval_result, f, ensure_ascii=False, indent=2)

        # 为当前 group 创建唯一的 session_id 标识
        session_id_str = f"human_group_{player.group.id}"
        save_response = api_save(base_url, session_id_str, eval_result)
        
        if save_response.get("status") == "success":
            log.info(f"Successfully saved to venus_api_server at {save_response.get('saved_path')}")
        else:
            log.error(f"Failed to save via venus_api_server: {save_response}")
        # ====================================================
        
    except Exception as e:
        log.error(f'Evaluation error: {e}', exc_info=True)
        player.group.eval_result_json = json.dumps({
            '_error': str(e),
            'summary': {
                'Acc_profile': 0,
                'Acc_valuebench': 0,
                'MAE_valuebench': 0,
                'Acc_decision': 0,
            }
        }, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Pages
# ══════════════════════════════════════════════════════════════════════════════

class RoleAnnounce(otree.Page):
    """告知角色，A 和 B 看到完全不同的说明。"""

    @staticmethod
    def vars_for_template(player: Player):
        cond = _condition(player)
        return {
            'is_A':      _is_A(player),
            'is_B':      _is_B(player),
            'max_turns': _max_turns(player),
            'condition': cond,
        }


# ── B: Profile ────────────────────────────────────────────────────────────────
class ProfileForm(otree.Page):
    form_model  = 'player'
    form_fields = [
        'p_name','p_age','p_gender','p_birthplace','p_graduate_school',
        'p_nationality','p_married','p_education','p_occupation',
        'p_income_level','p_has_children',
    ]

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player)

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        # Generate scenarios for B (synchronous)
        # base_url  = _api_base(player)
        # profile   = _b_profile(player)
        # scenarios = api_generate_scenarios(base_url, profile)
        # # scenarios = DEFAULT_SCENARIOS
        # player.group.scenarios_json = json.dumps(
        #     scenarios or DEFAULT_SCENARIOS, ensure_ascii=False)
        player.group.b_profile_ready = True
        if not player.group.baseline_session_id:
            player.group.baseline_session_id = str(uuid.uuid4())


# ── B: Wait while generating scenarios ──────────────────────────────────────
class WaitScenario(otree.Page):
    """
    B 填完档案后，系统生成个性化场景，显示加载界面。
    """
    title_text = '系统正在准备中'
    
    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player)

    @staticmethod
    def vars_for_template(player: Player):
        return {
            'waiting_msg': '系统正在准备中……',
        }

    @staticmethod
    def live_method(player: Player, data: dict):
        """处理前端的生成场景请求"""
        action = data.get('action', '')
        
        if action == 'generate_scenarios':
            base_url = _api_base(player)
            profile = _b_profile(player)
            
            try:
                # scenarios = api_generate_scenarios(base_url, profile)
                scenarios = DEFAULT_SCENARIOS
                player.group.scenarios_json = json.dumps(
                    scenarios or DEFAULT_SCENARIOS, ensure_ascii=False)
                player.group.b_profile_ready = True
                log.info(f'[WaitScenario] Group {player.group.id}: '
                        f'Generated {len(scenarios or DEFAULT_SCENARIOS)} scenarios.')
                
                return {player.id_in_group: {
                    'type': 'success',
                    'scenarios_count': len(scenarios or DEFAULT_SCENARIOS)
                }}
            except Exception as e:
                log.error(f'[WaitScenario] Error: {e}')
                # 降级到默认场景
                player.group.scenarios_json = json.dumps(DEFAULT_SCENARIOS, ensure_ascii=False)
                player.group.b_profile_ready = True
                return {player.id_in_group: {
                    'type': 'fallback',
                    'msg': f'场景生成失败，已使用默认场景: {str(e)}'
                }}
        
        return {player.id_in_group: {'type': 'noop'}}

# ── A: Wait for B to fill profile ─────────────────────────────────────────────
class WaitProfileDone(otree.WaitPage):
    title_text   = '等待对方准备就绪'
    body_text    = '请稍候，正在为本次实验做准备……（通常需要 2-3 分钟）'

    @staticmethod
    def after_all_players_arrive(group: Group):
        # Triggered when BOTH players reach this WaitPage.
        # B already set b_profile_ready in ProfileForm.before_next_page.
        # Nothing else needed; oTree releases everyone automatically.
        pass


# ── B: Questionnaire BEFORE chat (adversarial) OR AFTER (natural) ─────────────
# We handle this via is_displayed + page order:
# In adversarial condition: Questionnaire page appears BEFORE HumanChat
# In natural condition:     Questionnaire page appears AFTER HumanChat
# We use TWO page slots with is_displayed controlling which fires.

class QuestionnairePre(otree.Page):
    """B fills questionnaire BEFORE chat (adversarial condition only)."""
    form_model  = 'player'
    form_fields = ['questionnaire_scores_json']

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player) and _condition(player) == 'adversarial'

    @staticmethod
    def vars_for_template(player: Player):
        return {
            'questions':       FLAT_QUESTIONS,
            'total_questions': TOTAL_QUESTIONS,
            'is_pre':          True,
        }

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        try:
            scores = json.loads(player.questionnaire_scores_json or '{}')
        except Exception:
            scores = {}
        player.true_values_json = json.dumps(
            compute_true_values_local(scores), ensure_ascii=False)


class ScenariosPre(otree.Page):
    """B fills scenarios BEFORE chat (adversarial condition only)."""
    form_model  = 'player'
    form_fields = ['scenario_decisions_json']

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player) and _condition(player) == 'adversarial'

    @staticmethod
    def vars_for_template(player: Player):
        try:
            sc = json.loads(player.group.scenarios_json or '[]')
        except Exception:
            sc = DEFAULT_SCENARIOS
        return {'scenarios': sc or DEFAULT_SCENARIOS, 'total': len(sc or DEFAULT_SCENARIOS)}


class AdversarialBriefing(otree.Page):
    """告知 B 对抗规则（adversarial only）。"""

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player) and _condition(player) == 'adversarial'

    @staticmethod
    def vars_for_template(player: Player):
        return {'max_turns': _max_turns(player)}


# ── B: Chat1 with Baseline AI ─────────────────────────────────────────────────
class Chat1(otree.Page):
    """B 与 Baseline AI 对话（A 侧在 WaitChat1 等待）。"""

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player)

    @staticmethod
    def vars_for_template(player: Player):
        base_url = _api_base(player)
        profile  = _b_profile(player)
        tv       = json.loads(player.true_values_json or '{}')
        result   = api_create_session(base_url, profile, tv, 'baseline')
        player.group.baseline_session_id = result.get('api_session_id', '')
        first_q  = result.get('first_question', '你好！我们来聊聊吧。')
        hist     = [{'role': 'assistant', 'content': first_q}]
        player.chat1_history_json = json.dumps(hist, ensure_ascii=False)
        return {
            'first_question': first_q,
            'max_turns':      _max_turns(player),
            'api_session_id':     player.group.baseline_session_id,
            'prober_label':   '聊天对象',
        }

    @staticmethod
    def live_method(player: Player, data: dict):
        action = data.get('action', '')
        base_url = _api_base(player)
        if action == 'send_message':
            text = data.get('text', '').strip()
            if not text:
                return {player.id_in_group: {'type': 'error', 'msg': '请输入内容'}}
            sid   = player.group.baseline_session_id
            max_t = _max_turns(player)
            resp  = api_chat(base_url, sid, text, max_t)
            reply = resp.get('reply', '')
            step  = resp.get('step', 0)
            done  = resp.get('done', False)
            hist  = json.loads(player.chat1_history_json or '[]')
            hist.append({'role': 'user', 'content': text})
            if reply:
                hist.append({'role': 'assistant', 'content': reply})
            player.chat1_history_json = json.dumps(hist, ensure_ascii=False)
            player.chat1_turns = step
            if done:
                fin = api_finalize(base_url, sid)
                player.chat1_value_state_json = json.dumps(
                    fin.get('value_state', {}), ensure_ascii=False)
                player.group.b_chat1_done = True
            return {player.id_in_group: {
                'type': 'message', 'reply': reply, 'step': step, 'done': done}}
        elif action == 'done':
            if player.group.baseline_session_id:
                fin = api_finalize(base_url, player.group.baseline_session_id)
                player.chat1_value_state_json = json.dumps(
                    fin.get('value_state', {}), ensure_ascii=False)
            player.group.b_chat1_done = True
            return {player.id_in_group: {'type': 'advance'}}
        return {player.id_in_group: {'type': 'noop'}}


class WaitChat1(otree.WaitPage):
    """A 等待 B 完成 Chat1。"""
    title_text = '等待第一次对话完成'
    body_text  = '您的搭档正在进行第一次对话，请稍候……'

    @staticmethod
    def is_displayed(player: Player):
        # A waits; B passes through instantly (already done)
        return _is_A(player)


class Chat1Rating(otree.Page):
    form_model  = 'player'
    form_fields = [
        'chat1_naturalness', 'chat1_stealthiness',
        'chat1_responsiveness', 'chat1_topic_flow', 'chat1_suspicion_text',
    ]

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player)

    @staticmethod
    def vars_for_template(player: Player):
        return {'chat_num': 1}


# ── CORE: Human A ↔ B Real-time Chat ─────────────────────────────────────────
class HumanChat(otree.Page):
    """
    A 和 B 实时对话的核心页面（回合制）。
    轮号规则：
      turn=0: A 可发送
      turn=1: B 可发送
      turn=2: A 可发送
      ...
      turn达到 max_turns*2 时，对话结束
    """

    @staticmethod
    def vars_for_template(player: Player):
        cond    = _condition(player)
        is_a    = _is_A(player)
        is_b    = _is_B(player)
        
        partner = player.get_others_in_group()[0]
        
        partner_info = {}
        if is_a:
            partner_info = {
                'name': partner.p_name or '未知',
                'age': partner.p_age or '未知',
                'gender': partner.p_gender or '未知',
                'birthplace': partner.p_birthplace or '未知',
                'graduate_school': partner.p_graduate_school or '未知',
                'nationality': partner.p_nationality or '未知',
                'married': partner.p_married or '未知',
                'education': partner.p_education or '未知',
                'occupation': partner.p_occupation or '未知',
                'income_level': partner.p_income_level or '未知',
                'has_children': partner.p_has_children or '未知',
            }

        return {
            'is_A':       is_a,
            'is_B':       is_b,
            'max_turns':  _max_turns(player),
            'nickname':   '对方',
            'condition':  cond,
            'group_id':   player.group.id_in_subsession,
            'partner_info': partner_info, # 将对方信息传给前端
        }

    @staticmethod
    def live_method(player: Player, data: dict):
        """
        处理发送消息、状态检查等。
        轮号管理：
          - 偶数轮（0,2,4...）：A 说话
          - 奇数轮（1,3,5...）：B 回答
        """
        action = data.get('action', '')
        group = player.group
        max_t = _max_turns(player)
        total_messages_needed = max_t * 2  # A和B各说max_t次
        
        if action == 'send_message':
            user_text = data.get('text', '').strip()
            if not user_text:
                return {player.id_in_group: {
                    'type': 'error',
                    'msg': '请输入内容'
                }}
            
            # ── 权限检查 ──
            is_a = _is_A(player)
            turn = group.human_chat_turn
            
            # 检查是否已经结束
            if turn >= total_messages_needed:
                session_id_str = f"human_group_{group.id}_chat"
                api_save(_api_base(player), session_id_str, {
                    'type': 'chat_message',
                    'dialogue_history': hist,
                })

                return {player.id_in_group: {
                    'type': 'error',
                    'msg': '对话已结束'
                }}
            
            # 检查是否轮到此人
            a_turn = (turn % 2 == 0)  # 偶数轮是 A
            if is_a != a_turn:
                return {player.id_in_group: {
                    'type': 'error',
                    'msg': '还没轮到您说话'
                }}
            
            # ── 记录消息 ──
            hist = json.loads(group.human_chat_history or '[]')
            hist.append({
                'role': 'A' if is_a else 'B',
                'content': user_text,
                'turn': turn
            })
            group.human_chat_history = json.dumps(hist, ensure_ascii=False)
            group.human_chat_turn = turn + 1
            session_id_str = f"human_group_{group.id}_chat"
            api_save(_api_base(player), session_id_str, {
                'type': 'chat_message',
                'dialogue_history': hist,
            })
            
            # ── 向双方广播消息 ──
            return {0: {
                'type': 'message',
                'sender': 'A' if is_a else 'B',
                'text': user_text,
                'turn': turn + 1,
                'total': total_messages_needed,
            }}
        
        elif action == 'check_status':
            turn = group.human_chat_turn
            is_done = turn >= total_messages_needed
            is_a = _is_A(player)
            a_turn = (turn % 2 == 0)
            can_send = (not is_done) and (is_a == a_turn)
            
            return {player.id_in_group: {
                'type': 'status',
                'turn': turn,
                'total': total_messages_needed,
                'is_done': is_done,
                'can_send': can_send,
                'waiting_for': 'A' if a_turn else 'B',
            }}
        
        return {player.id_in_group: {'type': 'noop'}}

class WaitHumanChatDone(otree.WaitPage):
    """双方都标记完成后才放行。"""
    title_text = '等待对方完成对话'
    body_text  = '请等待对方也结束对话……'

    @staticmethod
    def after_all_players_arrive(group: Group):
        pass   # just synchronize


# ── B: Rating of Human A ──────────────────────────────────────────────────────
class Chat2Rating(otree.Page):
    form_model  = 'player'
    form_fields = [
        'chat2_naturalness', 'chat2_stealthiness',
        'chat2_responsiveness', 'chat2_topic_flow', 'chat2_suspicion_text',
    ]

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player)

    @staticmethod
    def vars_for_template(player: Player):
        return {'chat_num': 2}


# ── A: Value Prediction + Self Questionnaire + Scenario Prediction ─────────────
class ProberPredict(otree.Page):
    form_model  = 'player'
    form_fields = ['prober_predictions_json',
                   'prober_quest_scores_json',
                   'prober_scenario_dec_json']

    @staticmethod
    def is_displayed(player: Player):
        return _is_A(player)

    @staticmethod
    def vars_for_template(player: Player):
        value_dims = [
            {"name": "自我决定-思想", "desc": "自由思考、形成独创想法"},
            {"name": "自我决定-行动", "desc": "自主决定如何规划和行动"},
            {"name": "刺激", "desc": "寻求新奇、冒险与刺激体验"},
            {"name": "享乐主义", "desc": "享受生活、追求快乐与放松"},
            {"name": "成就", "desc": "取得成功、证明能力并获认可"},
            {"name": "权力-支配", "desc": "成为领导者、指挥/支配他人"},
            {"name": "权力-资源", "desc": "拥有财富、掌控昂贵物质资源"},
            {"name": "面子", "desc": "维护公众形象、避免被看不起"},
            {"name": "安全-个人", "desc": "生活环境安全、避免个人危险"},
            {"name": "安全-社会", "desc": "国家/社会稳定、抵御外部威胁"},
            {"name": "传统", "desc": "保持传统习俗、遵循家族传承"},
            {"name": "遵从-规则", "desc": "严格遵守规则/法律、绝不违规"},
            {"name": "遵从-人际", "desc": "避免惹恼他人、不冒犯身边人"},
            {"name": "谦逊", "desc": "保持低调谦逊、不张扬炫耀"},
            {"name": "仁慈-关爱", "desc": "关心和照顾亲近之人的福祉"},
            {"name": "仁慈-可靠", "desc": "成为值得信赖、让亲友可依靠的人"},
            {"name": "普世-关怀", "desc": "保护弱势群体、致力于社会公平"},
            {"name": "普世-自然", "desc": "保护生态环境、与自然和谐相处"},
            {"name": "普世-包容", "desc": "理解和包容不同信仰或观念的人"},
            {"name": "普世-客观", "desc": "依靠理性、证据寻找客观真理"}
        ]
        try:
            sc = json.loads(player.group.scenarios_json or '[]')
        except Exception:
            sc = []
        return {
            'questions':       FLAT_QUESTIONS,
            'total_questions': TOTAL_QUESTIONS,
            'value_dims':      value_dims,
            'scenarios':       sc or DEFAULT_SCENARIOS,
        }

    # @staticmethod
    # def before_next_page(player: Player, timeout_happened):
    #     # Check if B's questionnaire is also done; if so trigger evaluation, if not done, wait for it.
    #     b = _get_B(player.group)
    #     if b.scenario_decisions_json and b.scenario_decisions_json != '{}':
    #         _trigger_evaluation(player)
    #     else:
    #         log.info(f'ProberPredict: A finished predictions but waiting for B\'s data. Group {player.group.id}.')


# ── B: Questionnaire AFTER chat (natural condition) ────────────────────────────
class QuestionnairePost(otree.Page):
    form_model  = 'player'
    form_fields = ['questionnaire_scores_json']

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player) and _condition(player) == 'natural'

    @staticmethod
    def vars_for_template(player: Player):
        return {
            'questions':       FLAT_QUESTIONS,
            'total_questions': TOTAL_QUESTIONS,
            'is_pre':          False,
        }


class ScenariosPost(otree.Page):
    """B fills scenarios AFTER chat (natural condition)."""
    form_model  = 'player'
    form_fields = ['scenario_decisions_json']

    @staticmethod
    def is_displayed(player: Player):
        return _is_B(player) and _condition(player) == 'natural'

    @staticmethod
    def vars_for_template(player: Player):
        try:
            sc = json.loads(player.group.scenarios_json or '[]')
        except Exception:
            sc = []
        return {'scenarios': sc or DEFAULT_SCENARIOS, 'total': len(sc or DEFAULT_SCENARIOS)}

    # @staticmethod
    # def before_next_page(player: Player, timeout_happened):
    #     try:
    #         scores = json.loads(player.questionnaire_scores_json or '{}')
    #     except Exception:
    #         scores = {}
        
    #     print(f'[ScenariosPost] B\'s questionnaire scores: {scores}')
    #     player.true_values_json = json.dumps(
    #         compute_true_values_local(scores), ensure_ascii=False)
        # Check if A's predictions are also ready; if so trigger evaluation
        # a = _get_A(player.group)
        # b = _get_B(player.group)
        # if a.prober_predictions_json and a.prober_predictions_json != '{}':
        #     _trigger_evaluation(player)

# ── Wait for all data ready ────────────────────────────────────────────────────
class WaitAllDataDone(otree.WaitPage):
    """
    等待 A 和 B 都完成问卷（A: ProberPredict, B: QuestionnairePost + ScenariosPost）。
    然后在 after_all_players_arrive 中触发评估。
    """
    title_text = '等待数据收集完成'
    body_text  = '双方均已提交问卷，系统正在分析数据……'

    @staticmethod
    def after_all_players_arrive(group: Group):
        """当双方都到达此等待页时，触发评估。"""
        # 找到任一玩家（都可以，他们在同一 group）
        player = group.get_players()[0]
        _trigger_evaluation(player)
        log.info(f'[WaitAllDataDone] Group {group.id} evaluation triggered.')


# ── Debrief ───────────────────────────────────────────────────────────────────
class Debrief(otree.Page):
    @staticmethod
    def vars_for_template(player: Player):
        is_a = _is_A(player)
        try:
            eval_scores = json.loads(player.group.eval_result_json or '{}')
        except Exception:
            eval_scores = {}
        acc = (eval_scores.get('interaction', {})
               .get('value_prediction_accuracy', None))
        return {
            'is_A':      is_a,
            'is_B':      _is_B(player),
            'condition': _condition(player),
            'accuracy':  f'{acc:.1%}' if acc is not None else '计算中…',
        }


# ══════════════════════════════════════════════════════════════════════════════
# Page sequence
# ══════════════════════════════════════════════════════════════════════════════
# is_displayed controls what each role actually sees.
# WaitPages synchronize the two roles.

page_sequence = [
    RoleAnnounce,        # ALL: intro + role reveal
    ProfileForm,         # B only: fill profile + generate scenarios
    WaitScenario,        # B only: wait while system generates scenarios
    WaitProfileDone,     # ALL: sync after B fills profile
    # ── Adversarial pre-chat questionnaire ──
    QuestionnairePre,    # B only, adversarial: questionnaire before chat
    ScenariosPre,        # B only, adversarial: scenarios before chat
    AdversarialBriefing, # B only, adversarial: reveal the adversarial rule
    # ── Chat 1: Baseline AI ──
    # Chat1,               # B only: chat with baseline AI
    # Chat1Rating,         # B only: rate Chat1
    # WaitChat1,           # A only: wait for B to finish Chat1
    # ── Chat 2: Human A ↔ B ──
    HumanChat,           # ALL: real-time A↔B chat via {{ chat }}
    WaitHumanChatDone,   # ALL: sync when both mark done
    Chat2Rating,         # B only: rate human A
    # ── Post-chat data collection ──
    ProberPredict,       # A only: 20-dim prediction + self questionnaire + scenario pred
    QuestionnairePost,   # B only, natural: questionnaire after chat
    ScenariosPost,       # B only, natural: scenarios after chat
    WaitAllDataDone,     # ALL: sync after both complete questionnaires, then trigger evaluation
    Debrief,             # ALL: reveal + accuracy
]
