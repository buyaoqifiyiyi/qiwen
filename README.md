# 启问 · Qiwen

启问 0.9.1 是原「提示词增强 · Prompt Craft」的后续版本，以 Agent Skill 形式提供提示词改写、任务澄清和方案质询。

- 项目创建、优化、排查、具体方案和多步内容任务可以先整理目标、范围和验收，再继续执行。
- 说「只给提示词」时，直接交付可复制的提示词。
- 说「grill me」或「质询」时，聚焦会改变结果的决策。用户明确要求全面质询时，按决策依赖逐步推进。

## 安装

让 Agent 从本仓库安装 [`skills/qiwen`](skills/qiwen/) 目录，保留整个 `qiwen` 目录及内部文件。也可以先克隆仓库，再将 `skills/qiwen` 复制到宿主支持的技能目录。

```bash
git clone https://github.com/buyaoqifiyiyi/prompt-craft.git
```

例如，Codex 的用户级目录为 `~/.agents/skills/qiwen/`。重新打开会话后，可以用 `$qiwen` 显式调用。已经装过 Prompt Craft 插件的用户可先验证新 Skill 能加载，再停用旧插件，避免两套规则同时触发。

如果希望宿主稳定地在实质任务前应用启问，可以在宿主的 Agent 指令中加入以下规则，并让每个 Agent 使用其已配置的 Skill 目录。

> 新任务涉及项目创建或优化、具体故障诊断、具体评审或方案、多步内容时，先读取启问的 SKILL.md，整理目标、范围和验收后继续原任务。关键用户决策缺失时才澄清。普通聊天、简单问答、进度查询和明确单点操作直接处理。用户明确只要提示词时，只交付提示词。

## Yanlu 联动

提示词增强和启问内的质询可独立使用。工程中途共用质询规则、交接和项目留档，需要在同一 Skill 根目录安装带有启问联动的 Yanlu。兼容的 Yanlu 应在 `modules/grilling/GUIDE.md` 引用启问的 `references/grilling.md`，并在 `modules/domain-modeling/GUIDE.md` 包含「接收启问交接」一节。

当前公开的 Yanlu 主分支仍使用原有质询规则。完整联动已在本机配套版本验证。用户明确请求交接时，默认在对话中整理已确认的术语、决策和理由。明确授权写入目标项目时，才按项目约定更新词汇表和 ADR。

## 回归与版本

[回归用例](skills/qiwen/tests/README.md)覆盖自动触发、仅交付提示词、工程中途质询、聊天交接、临时项目留档和简单任务旁路。运行器需要本机 Codex，完整套件还需配套 Yanlu 和宿主路由指令。

[来源与许可声明](skills/qiwen/SOURCES.md)和[第三方许可](skills/qiwen/LICENSES/)随包提供。原 Prompt Craft 0.8.0 插件可从[历史提交](https://github.com/buyaoqifiyiyi/prompt-craft/tree/faecca90d372b289e7382ba49524fb4d95f21d4f)查看。
