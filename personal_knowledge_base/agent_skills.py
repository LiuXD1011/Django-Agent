"""
Agent Skills 系统

参考 WeKnora 的 agent/skills/ 设计，实现渐进式披露（Progressive Disclosure）：
- Level 1: 启动时加载所有 skill 的名称和描述
- Level 2: 通过 read_skill 工具按需加载完整指令
- Level 3: 通过 read_skill_file 工具按需加载附加资源

Skill 文件格式：SKILL.md（YAML frontmatter + Markdown body）
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent / "skills"


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    instructions: str = ""
    loaded: bool = False

    def to_metadata(self) -> dict:
        return {"name": self.name, "description": self.description}


class SkillsManager:
    def __init__(self, skills_dir: Path | None = None):
        self.skills_dir = skills_dir or SKILLS_DIR
        self._skills: dict[str, Skill] = {}

    def discover(self):
        """发现所有 skill（Level 1：加载元数据）。"""
        if not self.skills_dir.exists():
            return

        for skill_file in self.skills_dir.glob("*/SKILL.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        meta = yaml.safe_load(parts[1]) or {}
                        skill = Skill(
                            name=meta.get("name", skill_file.parent.name),
                            description=meta.get("description", ""),
                            path=skill_file.parent,
                        )
                        self._skills[skill.name] = skill
            except Exception:
                logger.exception(f"Failed to load skill metadata from {skill_file}")

    def list_skills(self) -> list[dict]:
        """返回所有 skill 的元数据（Level 1）。"""
        return [s.to_metadata() for s in self._skills.values()]

    def load_skill(self, name: str) -> Skill | None:
        """加载 skill 的完整指令（Level 2）。"""
        skill = self._skills.get(name)
        if not skill:
            return None

        if skill.loaded:
            return skill

        try:
            content = skill.path.joinpath("SKILL.md").read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    skill.instructions = parts[2].strip()
                    skill.loaded = True
        except Exception:
            logger.exception(f"Failed to load skill instructions for {name}")

        return skill

    def read_skill_file(self, name: str, filename: str) -> str | None:
        """读取 skill 的附加资源文件（Level 3）。"""
        skill = self._skills.get(name)
        if not skill:
            return None

        file_path = skill.path / filename
        if not file_path.exists() or not file_path.is_file():
            return None

        # 安全检查：防止路径遍历
        try:
            file_path.resolve().relative_to(skill.path.resolve())
        except ValueError:
            return None

        try:
            return file_path.read_text(encoding="utf-8")
        except Exception:
            logger.exception(f"Failed to read skill file {filename} for {name}")
            return None


# 全局实例
_manager: SkillsManager | None = None


def get_skills_manager() -> SkillsManager:
    global _manager
    if _manager is None:
        _manager = SkillsManager()
        _manager.discover()
    return _manager
