# agent-ci-starter

**把“升级前检查工具接口”和“运行后检查调用记录”放进一个能直接体验的项目。**

[English](README.md) · [查看 GitHub 自动检查](https://github.com/L1Huash1/agent-ci-starter/actions)

假设你维护一个会调用工具的 Agent：升级工具时，原来的参数可能不再适用；运行时，也可能出现重复失败或未完成调用。这个入门项目把两个现有小工具串起来，展示如何在 GitHub 自动检查中发现这些信号。

示例使用实际执行的本地 Python 函数，流程由脚本预先安排。它不包含自主规划的大模型 Agent，不用模型、API Key 或 MCP 服务。安装时需要下载源码依赖，示例和诊断在本地运行。

## 在本地体验

测试使用 Python 3.13 和 Git。可以先创建并激活虚拟环境，然后运行：

```sh
git clone https://github.com/L1Huash1/agent-ci-starter.git
cd agent-ci-starter
python -m pip install -r requirements.txt

# 检查升级前后的接口，初始示例没有变化，应该通过
mcp-changecheck contracts/baseline.json contracts/candidate.json

# 实际执行“读取笔记”和“统计字数”，记录两次调用
python demo.py trace.jsonl

# 检查调用次数和错误预算，应该通过
agent-tracecheck trace.jsonl --max-calls 4 --max-errors 0
```

依赖固定到两个工具已经发布的 GitHub 源码版本，不要求它们已在 PyPI 上架。记录器拒绝覆盖现有文件，重复体验时请换一个输出文件名。

## 看看失败时是什么样

```sh
# 这个快照故意删除工具、增加必填参数，返回 1 是预期结果
mcp-changecheck contracts/baseline.json contracts/breaking.json

# 故意增加三次相同的失败调用，保存成另一份记录
python demo.py retry-trace.jsonl --scenario retry

# 错误超过默认预算，返回 1 是预期结果
agent-tracecheck retry-trace.jsonl
```

想只看报告，可以在诊断命令后加 `--fail-on never`。输入文件本身无效时仍返回 2。这些失败由示例故意制造，不是大模型能力或性能评测。

## 可选体验：上下文与故障恢复实验

新实验把 [context-budgetpack](https://github.com/L1Huash1/context-budgetpack)、[tool-mockbox](https://github.com/L1Huash1/tool-mockbox) 和原来的调用记录器连起来。它先根据明确清单整理合成笔记和代码片段，再调用一个预先安排“前两次临时失败、第三次成功”的模拟工具。上下文供你查看，**不会发给模型**。

```sh
python -m pip install -r requirements-lab.txt
python lab.py --output lab-output
```

可选依赖包含原来的两个工具和新工具，全部固定到已经复核的 GitHub 源码提交。安装完成后，实验不需要联网，不调用模型或付费 API。打开 `lab-output/trace-report.html` 即可查看和跳转到各份报告。重复运行时请换一个输出目录，已有文件不会被覆盖。

| 产物 | 可以看到什么 |
| --- | --- |
| `context/report.html` | 合成笔记和代码在 1600 字节上限内如何被选择 |
| `fixture-run.json` / `.html` | 模拟工具的两次失败、一次成功及响应内容 |
| `trace.jsonl` | 记录器实际产生的原始调用与结果事件 |
| `trace-report.json` / `.md` | 已安装的 agent-tracecheck 命令生成的诊断 |
| `trace-report.html` | 本入门项目附带的诊断查看页，不是模型能力评测 |
| `lab-summary.json` | 尝试次数、恢复结果、上下文字节和诊断状态 |

默认最多尝试 3 次，可设置为 1–10 次。只重试明确标为 `temporary` 的 `MockToolError`。工具不存在、参数不匹配、脚本步骤耗尽或其他错误会立即停止。失败运行也会保留报告并返回 1；无效输入或文件错误返回 2。写入中断可能留下不完整的新目录。

默认诊断预算明确允许这份脚本预设的 2 次失败、3 次调用，但重试和重复调用提醒仍会显示，最终成功也不能跳过预算检查。真实业务应自行制定容错规则。运行 `python lab.py --output stopped-lab --max-attempts 2` 会在恢复前停止，返回 1 是预期结果。

## 复制到自己的 GitHub 项目

Fork 或复制本仓库，启用 [自动检查工作流](.github/workflows/checks.yml)。它会在 Windows 和 Linux 上：

1. 通过已发布的 `L1Huash1/mcp-changecheck@v0.3.0` 检查接口快照，并在运行摘要里显示报告。
2. 安装固定版本的工具，运行六项回归测试，执行本地示例，再检查调用和错误预算。
3. `recovery-lab` 任务运行可选实验的十一项端到端测试，并上传合成实验报告。可在成功运行的 **Artifacts** 下载，保留 7 天。

只需要仓库读取权限，不需要密钥或写权限。上传范围仅为生成的合成 `lab-output/` 目录。接入自己的项目时，替换候选快照，连接实际工具调用；基线变化需要认真复核。此处快照描述的是本地函数的接口，使用 MCP 快照结构，并非从实际运行的 MCP 服务导出。未安装可选依赖时，原来的六项测试仍运行，实验测试会跳过。

工具能力边界和更多说明见 [mcp-changecheck](https://github.com/L1Huash1/mcp-changecheck)、[agent-tracecheck](https://github.com/L1Huash1/agent-tracecheck)。接口静态检查不能证明完全兼容，调用诊断也不能评价模型回答的质量。

MIT 许可证；初始开发使用 AI 编程辅助。
