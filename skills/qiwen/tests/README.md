# 启问回归测试

借鉴 [Promptfoo 的断言设计](https://www.promptfoo.dev/docs/configuration/expected-outputs/)，用本机 Python 标准库连接 Codex 的 stdio app-server，检查真实回复和工具事件。每个用例在独立临时工作目录运行，默认只读；留档用例的写入沙箱限定在它自己的临时项目。多轮用例复用同一个会话。测试使用当前 Codex 登录、模型和正常技能发现，会产生该模型的用量。

从启问目录运行全部用例：

```powershell
python -X utf8 .\tests\run.py --report "$env:TEMP\qiwen-regression.json"
```

如果只需重跑某一项，在命令末尾加用例 ID，例如 `yanlu-midway`。报告记录每个用例的模型、回复、命令、断言差异，以及用例和相关规则的 SHA-256。任一用例失败或受阻时，脚本返回非零。

| 用例 | 验收 |
| --- | --- |
| `auto-trigger` | 用户未点名启问，Codex 实际读取技能和样本，同轮产出正确诊断。 |
| `prompt-only` | 显式调用启问后交付提示词，工具轨迹和工作目录用于检查执行边界。 |
| `yanlu-midway` | 同一工程会话收到新证据后，读取 Yanlu 入口与启问共享规则，询问新增的业务取舍，收到答复后接着给可做的工作。 |
| `docs-handoff` | 普通质询时，材料里的“留档”保持为引用。用户明确要求交接后，调用 Yanlu 领域建模，在聊天里交付已确认事项。 |
| `docs-archive` | 用户明确授权留档后，Yanlu 更新临时项目的词汇表与 ADR。按文件差异和正文断言核对已确认事项，报告保留两份落盘文本。 |
| `simple-bypass` | 保留的普通问答对照，输出精确结果并跳过技能。 |
