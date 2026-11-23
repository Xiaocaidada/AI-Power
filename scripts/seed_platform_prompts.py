"""Seed platform Prompt Lab templates (idempotent)."""

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import PromptTemplate, PromptVersion

TEMPLATES = [
    (
        "代码分析",
        "分析代码质量、风险与改进点。",
        "你是一名资深软件工程师。请分析用户提供的代码，指出问题、风险和改进建议。",
        "请分析以下代码：\n\n{{input}}",
    ),
    (
        "代码生成",
        "根据需求生成可运行的代码。",
        "你是一名资深工程师。请生成简洁、可运行的代码，并说明关键设计。",
        "需求：\n{{input}}",
    ),
    (
        "技术文档总结",
        "把长文档压缩成结构化摘要。",
        "你是一名技术文档编辑。请输出结构化摘要，保留关键结论与数字。",
        "请总结以下文档：\n\n{{input}}",
    ),
    (
        "文本润色",
        "改善表达、语气与结构。",
        "你是一名中文编辑。请在不改变事实的前提下润色文本。",
        "请润色以下文本：\n\n{{input}}",
    ),
    (
        "数据分析",
        "从数据中提炼趋势与异常。",
        "你是一名数据分析师。请基于输入数据给出趋势、异常和可执行建议。",
        "数据与背景：\n{{input}}",
    ),
    (
        "结构化信息提取",
        "提取字段并输出 JSON。",
        "你是一名信息抽取助手。请只输出 JSON，不要解释。",
        "请从以下内容中提取字段：\n\n{{input}}",
    ),
    (
        "学习辅导",
        "用循序渐进的方式解释概念。",
        "你是一名耐心的导师。请用例子和步骤解释概念，并给出练习。",
        "我想学习：{{input}}",
    ),
    (
        "内容创作",
        "生成有结构、有语气的内容。",
        "你是一名内容创作者。请根据主题生成有结构、有感染力的内容。",
        "主题与要求：\n{{input}}",
    ),
]


async def main() -> None:
    async with SessionLocal() as session:
        existing = set(
            (
                await session.execute(
                    select(PromptTemplate.name).where(
                        PromptTemplate.scope == "platform",
                        PromptTemplate.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        created = 0
        for name, description, system_prompt, user_prompt in TEMPLATES:
            if name in existing:
                continue
            template = PromptTemplate(
                workspace_id=None,
                scope="platform",
                name=name,
                description=description,
                category="platform",
            )
            session.add(template)
            await session.flush()
            session.add(
                PromptVersion(
                    template_id=template.id,
                    version=1,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    variables=["input"],
                    variable_definitions=[
                        {
                            "name": "input",
                            "description": "User input",
                            "required": True,
                            "default": "",
                        }
                    ],
                    parameters={},
                )
            )
            created += 1
        await session.commit()
        print(f"platform prompts created: {created}")


if __name__ == "__main__":
    asyncio.run(main())