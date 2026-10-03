# MCP Server 安装与接入

[REPO] 本包提供 BOM/CAD 整理、板与 MARK/拼板/BAD MARK 配置、元件库读取/编辑/复制、人工确认关联数据库、YGX/FDX 导出和本机 YSUP 线体优化。运行代码与现有 MCP Server 相同，未包含客户文件、项目数据库、已确认生产库、录像或 YSUP 安装程序。

## 安装

[REPO] 使用 Windows 和 Python 3.12。线体优化需要本机已安装、可运行的 YSUP，并已配置机台顺序、供料装置和保存的 `.ygs` 优化设置。其他编程工具可在未配置 YSUP 时使用。

在解压或克隆后的项目根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\generate_mcp_config.py --ysup-root '<本机 YSUP 安装目录>'
```

[REPO] pip 安装需要访问依赖下载源。依赖来自 requirements.txt，没有附带 Python 或第三方安装包。暂不接入优化时省略 `--ysup-root`。

## MCP 客户端

[REPO] 生成的 `mcp_config.local.json` 含 `mcpServers` 配置：当前 Python 绝对路径、`run_mcp.py` 绝对路径、项目数据目录、确认关联库路径及优化工作目录。提供 YSUP 参数时写入 `YAMAHA_YSUP_ROOT`。安装位置变化后重新生成配置。

把其中的服务项加入支持 stdio MCP 的客户端；无需先启动网页服务器。[UNKNOWN] DSH 的实际配置界面及 DeepSeek 模型调用效果尚未验收，通用 MCP 配置示例不能代替客户端实测。

[REPO] 网页人工核对入口：双击 Start-Builder.cmd，或运行 `.\.venv\Scripts\python.exe -m builder --open`。网页与 MCP 默认使用同一 `data` 目录。

HTTP 模式可选：

```powershell
.\.venv\Scripts\python.exe run_mcp.py --transport streamable-http --port 8766
```

[REPO] 端点为 `http://127.0.0.1:8766/mcp`，仅绑定本机回环地址。本服务可读取客户端指定的本机文件并写出程序，客户端应部署在能访问输入、输出和 YSUP 安装的电脑上。

## 线体优化

1. 调用 `list_optimization_lines`，取得本机已配置的线体、机台顺序和保存设置。
2. 对人工核对并保存后的 YGX 调用 `start_line_optimization`，传入实际 `file_path`、列表中的 `line`、`settings_name` 和唯一 `request_id`。
3. 使用返回的 `job_id` 调用 `get_line_optimization`。只有 `status=succeeded` 且 `mounts_identical=true` 才交付 `outputs` 中的分机文件。

[REPO] 每个优化任务在工作目录的 YSUP 副本中执行。未完成任务、失败任务及供料配置错误不能视为优化成功。本包没有重新分配设备能力的独立算法，实际优化由安装的 YSUP 执行。

## 确认关联库

[REPO] 人工确认并保存元件修改后，使用 `confirm_library_associations` 归档指定物料组、最终 YGX 和确认依据。保存或优化成功本身不构成人工确认。

[REPO] 下次用 `query_library_associations` 按物料身份和机型/供料范围精确查询，唯一适用时调用 `apply_library_associations` 和 `match_part`；冲突、缺参数或托盘机台条件待人工处理。

[REPO] 项目保存在 `data/projects.sqlite3`，确认历史保存在 `data/confirmed_associations.sqlite3`。跨项目使用同一 `YAMAHA_ASSOCIATIONS_DB`；关停相关服务后备份该文件。GitHub 包不包含现有生产关联记录，需要从自己的本机备份迁移。

## 验证

```powershell
.\.venv\Scripts\python.exe tools\check_package.py
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

[REPO] 包内检查核对源码 SHA256、真实 stdio 握手、工具发现、隔离项目与板信息保存、模板读取和确认库接口。包内优化器测试使用合成安装和模拟进程，不运行真实机台。原开发目录另有客户夹具回归测试，客户夹具不随包上传。

[UNKNOWN] 换机后的原生 YSUP、实际线体、吸嘴/供料/视觉和生产原点必须现场验证；离线生成或优化成功不等于可直接上机。

## 许可与第三方资料

[REPO] 项目代码采用 MIT License，见 LICENSE。YSUP 安装程序、原生优化器和厂家帮助图示不随开源包分发；其许可与 Yamaha 商标不属于本项目 MIT 授权。使用者需自行安装并合法使用 YSUP。

[REPO] 开源包的参考图目录使用空 catalog，界面继续显示本项目的通用尺寸图和参数编辑。`assets` 保留生成程序所需的空 YGX 结构及离线 XML 数据模板；这些不包含客户元件库、贴装记录或 YSUP 可执行程序。默认工艺参数仍需核对，用户可通过 `import_ygx_template`、`import_mark_templates` 导入自己的已确认模板。
