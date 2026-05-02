# settings.py  —  oTree 5.10.0
# ─────────────────────────────────────────────────────────────────────────────
# 共 3 个 App：
#   value_probe_natural     — Condition A（自然社交）：AI 探测者（solo B session）
#   value_probe_adversarial — Condition B（对抗防御）：AI 探测者（solo B session）
#   value_probe_human       — 真人 A+B 配对（PLAYERS_PER_GROUP=2）
#                             通过 session.config['condition'] 区分 natural/adversarial
#
# 见数平台发布规则：
#   • AI 探测者组（natural/adversarial + doubao/prober8b）：每组 1 人，B 独立完成
#   • 真人配对组（human）：每组 2 人，见数"每组人数"设为 2
# ─────────────────────────────────────────────────────────────────────────────

from os import environ

_API = environ.get('VENUS_API_URL', 'http://123.57.39.204:10080/')

SESSION_CONFIGS = [
    dict(
        name='natural_human',
        display_name='Social Connection Study',
        app_sequence=['value_probe_human'],
        num_demo_participants=2,
        condition='natural',
        max_chat_turns=20,
        api_base_url=_API,
    ),
]

SESSION_CONFIG_DEFAULTS = dict(
    real_world_currency_per_point=1,
    participation_fee=0,
    doc='',
)

# PARTICIPANT_FIELDS：跨页面传递的参与者级变量
# value_probe_human 把数据存在 Player/Group 字段，不需要 participant 级字段
PARTICIPANT_FIELDS = []

LANGUAGE_CODE          = 'zh-hans'
REAL_WORLD_CURRENCY_CODE = 'CNY'
USE_POINTS             = False
ROOMS                  = []
ADMIN_USERNAME         = 'admin'
ADMIN_PASSWORD         = environ.get('OTREE_ADMIN_PASSWORD', 'value2025')
SECRET_KEY             = environ.get('OTREE_SECRET_KEY',    '8_value_probe_secret_2025')

DEMO_PAGE_INTRO_HTML = """
<h3>价值观探测人类实验平台</h3>
<ul>
  <li><b>A组（自然）</b>：掩护故事 + 社交好感度激励</li>
  <li><b>B组（对抗）</b>：先做问卷 + 明确隐藏激励</li>
  <li>每组包含：豆包AI / Prober-8B / 真人探测者 三个子条件</li>
</ul>
<p>真人配对组每组需 2 名参与者（见数平台设置"每组人数=2"）。</p>
"""
