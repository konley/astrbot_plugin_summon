import json
import os

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register

DATA_DIR = os.path.join("data", "plugins", "astrbot_plugin_summon")
RULES_FILE = os.path.join(DATA_DIR, "rules.json")
DEFAULT_MESSAGE = "召唤"
DEFAULT_PREFIXES = ["at", "大召唤术"]

HELP_TEXT = (
    "大召唤术 v1.2.0\n"
    "在群内发送关键词自动艾特指定成员。\n\n"
    "命令前缀：/at 或 /大召唤术（均可使用）\n\n"
    "命令：\n"
    "/at add <关键词> [文案] @成员...   — 添加/更新召唤规则\n"
    "/at del <关键词>                    — 删除召唤规则\n"
    "/at list                           — 查看当前群的所有规则\n"
    "/at msg <关键词> [文案]            — 单独修改文案（不写恢复默认）\n"
    "/at delmsg <关键词>                — 清除自定义文案，恢复默认\n"
    "/at toggle                         — 切换权限模式（仅管理员）\n"
    "/at help                           — 显示此帮助\n\n"
    "示例：\n"
    "  /at add 开黑 @张三               — 关键词「开黑」，默认文案「召唤」\n"
    "  /at add 开黑 快来 @张三 @李四    — 关键词「开黑」，文案「快来」\n"
    "  /大召唤术 list                   — 用别名查看规则\n"
    "  已有关键词再次 add 会更新成员，保留原文案除非指定新文案\n\n"
    "权限说明：\n"
    "  everyone 模式：所有人可触发关键词，也可管理规则（toggle 除外）\n"
    "  admin_only 模式：仅管理员可触发关键词和管理规则"
)


def _load_rules() -> dict:
    if not os.path.exists(RULES_FILE):
        return {}
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[大召唤术] 读取规则文件失败: {e}")
        return {}


def _save_rules(rules: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


@register(
    "astrbot_plugin_summon",
    "konley",
    "大召唤术——群内发送关键词自动艾特指定成员。支持多群多关键词、自定义文案、权限控制、命令别名。",
    "1.2.0",
)
class SummonPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        config = config or {}
        self.permission_mode: str = config.get("permission_mode", "everyone")
        self.default_message: str = config.get("default_message", DEFAULT_MESSAGE)
        self.command_prefixes: list[str] = config.get(
            "command_prefixes", DEFAULT_PREFIXES
        )

    def _get_group_data(self, group_id: str) -> dict:
        rules = _load_rules()
        return rules.get(
            group_id, {"rules": {}, "permission_mode": self.permission_mode}
        )

    def _save_group_data(self, group_id: str, data: dict) -> None:
        rules = _load_rules()
        rules[group_id] = data
        _save_rules(rules)

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        if hasattr(event, "is_admin"):
            val = event.is_admin
            if callable(val):
                if val():
                    return True
            elif val:
                return True
        if hasattr(event, "role") and event.role in ("admin", "owner"):
            return True
        return False

    @staticmethod
    def _plain_text(event: AstrMessageEvent) -> str:
        return "".join(
            c.text for c in event.get_messages() if isinstance(c, Plain) and c.text
        )

    @staticmethod
    def _extract_ats(event: AstrMessageEvent) -> list[str]:
        self_id = str(event.get_self_id())
        return [
            str(c.qq)
            for c in event.get_messages()
            if isinstance(c, At) and str(c.qq) != self_id
        ]

    def _match_prefix(self, text: str) -> str | None:
        """匹配命令前缀，返回去掉前缀后的命令文本；不匹配返回 None"""
        for prefix in self.command_prefixes:
            full = f"/{prefix} "
            if text.startswith(full):
                return text[len(full):]
            # 也支持不带空格的 /at  直接跟子命令
            full_nospace = f"/{prefix}"
            if text == full_nospace:
                return ""
        return None

    # ── 主入口 ────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id:
            return
        group_id = str(group_id)
        text = self._plain_text(event).strip()
        if not text:
            return

        cmd_text = self._match_prefix(text)
        if cmd_text is not None:
            async for r in self._handle_command(event, group_id, cmd_text):
                yield r
            return

        async for r in self._handle_keyword(event, group_id, text):
            yield r

    # ── 命令处理 ──────────────────────────────────

    # 始终仅管理员可用的子命令
    ADMIN_ONLY_SUBCMDS = {"toggle"}

    async def _handle_command(
        self, event: AstrMessageEvent, group_id: str, cmd_text: str
    ):
        parts = cmd_text.split(maxsplit=1)
        subcmd = parts[0] if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        group_data = self._get_group_data(group_id)
        rules = group_data.get("rules", {})
        mode = group_data.get("permission_mode", self.permission_mode)
        is_admin = self._is_admin(event)

        # toggle 始终仅管理员可用
        if subcmd in self.ADMIN_ONLY_SUBCMDS and not is_admin:
            yield event.plain_result("只有群管理员才能切换权限模式。")
            return

        # admin_only 模式下，除 help/list 外所有命令仅管理员可用
        if mode == "admin_only" and subcmd not in ("help", "list") and not is_admin:
            yield event.plain_result("当前为仅管理员模式，只有群管理员才能使用此命令。")
            return

        if subcmd == "help" or not subcmd:
            yield event.plain_result(HELP_TEXT)
            return

        if subcmd == "add":
            if not rest:
                yield event.plain_result(
                    "请指定关键词。\n用法：/at add <关键词> [文案] @成员1 @成员2 ..."
                )
                return
            parts = rest.split(maxsplit=1)
            keyword = parts[0]
            # 文案：关键词之后、@成员之前的纯文本
            message = parts[1].strip() if len(parts) > 1 else ""
            members = self._extract_ats(event)
            if not members:
                yield event.plain_result(
                    "请艾特至少一个成员。\n用法：/at add <关键词> [文案] @成员1 @成员2 ..."
                )
                return
            # 覆盖保护：已有关键词更新成员时，保留原 message/enabled，除非指定了新文案
            existed = keyword in rules
            old_message = rules[keyword].get("message", self.default_message) if existed else (message or self.default_message)
            old_enabled = rules[keyword].get("enabled", True) if existed else True
            rules[keyword] = {
                "members": members,
                "message": message if message else old_message,
                "enabled": old_enabled,
            }
            self._save_group_data(group_id, group_data)
            mentions = " ".join(f"@{m}" for m in members)
            if existed:
                yield event.plain_result(f"已更新召唤规则：关键词「{keyword}」→ {mentions}")
            else:
                yield event.plain_result(f"已添加召唤规则：关键词「{keyword}」→ {mentions}")
            return

        if subcmd == "del":
            if not rest:
                yield event.plain_result(
                    "请指定要删除的关键词。\n用法：/at del <关键词>"
                )
                return
            keyword = rest.split()[0]
            if keyword not in rules:
                yield event.plain_result(f"关键词「{keyword}」不存在。")
                return
            del rules[keyword]
            self._save_group_data(group_id, group_data)
            yield event.plain_result(f"已删除关键词「{keyword}」的召唤规则。")
            return

        if subcmd == "list":
            if not rules:
                yield event.plain_result("当前群还没有设置任何召唤规则。")
                return
            lines = ["当前群的召唤规则："]
            for kw, rule in rules.items():
                members_str = " ".join(f"@{m}" for m in rule["members"])
                status = "[启用]" if rule["enabled"] else "[禁用]"
                msg = rule.get("message", "")
                if msg and msg != self.default_message:
                    msg_suffix = f" | 文案：{msg}"
                else:
                    msg_suffix = f" | 文案：{self.default_message}(默认)"
                lines.append(f"  {status} 「{kw}」→ {members_str}{msg_suffix}")
            mode = group_data.get("permission_mode", self.permission_mode)
            mode_text = "所有人" if mode == "everyone" else "仅管理员"
            lines.append(f"权限模式：{mode_text}")
            yield event.plain_result("\n".join(lines))
            return

        if subcmd == "msg":
            if not rest:
                yield event.plain_result(
                    "请指定关键词。\n用法：/at msg <关键词> [文案]（不写文案恢复默认）"
                )
                return
            msg_parts = rest.split(maxsplit=1)
            keyword = msg_parts[0]
            if keyword not in rules:
                yield event.plain_result(f"关键词「{keyword}」不存在。")
                return
            message = msg_parts[1] if len(msg_parts) > 1 else ""
            rules[keyword]["message"] = message
            self._save_group_data(group_id, group_data)
            label = message or f"{self.default_message}(默认)"
            yield event.plain_result(f"已设置关键词「{keyword}」的召唤文案为：{label}")
            return

        if subcmd == "delmsg":
            if not rest:
                yield event.plain_result("请指定关键词。\n用法：/at delmsg <关键词>")
                return
            keyword = rest.split()[0]
            if keyword not in rules:
                yield event.plain_result(f"关键词「{keyword}」不存在。")
                return
            rules[keyword]["message"] = ""
            self._save_group_data(group_id, group_data)
            yield event.plain_result(
                f"已恢复关键词「{keyword}」的默认文案「{self.default_message}」。"
            )
            return

        if subcmd == "toggle":
            current = group_data.get("permission_mode", self.permission_mode)
            new_mode = "admin_only" if current == "everyone" else "everyone"
            group_data["permission_mode"] = new_mode
            self._save_group_data(group_id, group_data)
            label = "仅管理员" if new_mode == "admin_only" else "所有人"
            yield event.plain_result(f"权限已切换为：{label}")
            return

        yield event.plain_result(f"未知子命令：{subcmd}\n使用 /at help 查看帮助。")

    # ── 关键词匹配 ────────────────────────────────

    async def _handle_keyword(self, event: AstrMessageEvent, group_id: str, text: str):
        group_data = self._get_group_data(group_id)
        rules = group_data.get("rules", {})

        if text not in rules:
            return

        rule = rules[text]
        if not rule.get("enabled", True):
            return

        mode = group_data.get("permission_mode", self.permission_mode)
        if mode == "admin_only" and not self._is_admin(event):
            return

        members = rule.get("members", [])
        if not members:
            return

        chain = []
        message = rule.get("message", "") or self.default_message
        chain.append(Plain(message + " "))
        for m in members:
            chain.append(At(qq=m))
            chain.append(Plain(" "))

        yield event.chain_result(chain)

    async def terminate(self):
        logger.info("[大召唤术] 插件已停止")
