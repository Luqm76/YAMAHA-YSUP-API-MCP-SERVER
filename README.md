# Yamaha Program Builder MCP Server

[REPO] 本机 BOM/CAD 整理、板信息与 MARK、元件库匹配/编辑、YGX/FDX 生成与 YSUP 线体优化。界面、REST 和 MCP 共用项目服务。安装包与 GitHub 部署方式见 [安装与接入](DEPLOYMENT.md)。

## 启动

双击 `Start-Builder.cmd`；或在本目录运行 `python -m builder --open`。
页面是 `http://127.0.0.1:8765`。运行窗口关闭或 Ctrl+C 后服务停止。
本机开发环境已安装依赖；换电脑安装 Python 3.12，再运行 `python -m pip install -r requirements.txt`。
`data/projects.sqlite3` 保存项目，删除会丢失本地项目；请用“下载完整项目”备份。

## 操作流程

1. 新建项目 → 填板宽、高、厚、加工面、输入坐标单位。默认保持坐标。背面不自动镜像。
2. 保存后进入 MARK 弹窗 → 填 2/3 个中心坐标、形状、尺寸、光源、阈值等。
3. 导入 BOM/CAD → 选字段按钮后点击列。表头行可重设；排除复选框可以取消/恢复行，原始数据不会删除。
4. 导入 ZIP/FDX/YGX 元件库 → 每个 BOM 物料选择完整参数。库的名称/封装候选需要明确确认。相同封装不同物料保持独立。
5. 可浏览/编辑元件参数，复制记录，或编辑完整 XML（含嵌套视觉参数）。这些修改仅保存到项目。
6. 校验与导出 → 生成 YGX、本项目 FDX 和清单；下载链接旁显示绝对路径。
7. 在 YSUP 基板编辑器人工核对并保存元件库后，通过 MCP 查询已配置线体、调用线体优化并检查分机结果。

### 拼板和辅助标记

打开“拼板 / 辅助标记”，先设置整板尺寸，再添加每块的 X/Y 偏移、角度及跳板选项。
辅助坐标统一使用相对 YGX 程序原点的 mm，不再套用 CAD 输入单位/镜像；点基准为贴装中心偏移。
基准类型包括块、局部、点、四点主/从；四点使用相邻两行，贴装点关联主行。
模板面板可编辑形状尺寸、视觉和照明参数，或导入完整 YGX/XML 模板。
辅助基准当前接受已核对的圆形/矩形模板；坏板模板使用独立 Mark_050/110/201 参数。
板坏标记决定是否搜索块坏标记；块坏标记跳过子板，局部坏标记通过位号关联跳过贴装点。
光学参数示例只用于离线流程验证，需按实际工艺设置。使用坏标记时输出关闭提前取料。
拼板输出一份基础贴装点与 Repeat 偏移，不自动展开复制；清单保存完整配置。
点基准的机型角度约定尚未核对，当前仅拒绝必然超出板框的巨大偏移；最终位置和光学范围需要 YSUP/机台检查。

[REPO] 开发夹具的工艺参数仅用于离线流程验证。分发包不附带客户 BOM/CAD、生产库或本机项目数据。

## 坐标和模板

板尺寸/原点偏移/MARK 形状尺寸始终为 mm；CAD 与 MARK 中心坐标按选定输入单位转换。
偏移先扣除，镜像/旋转再执行。YGX 输出保留 3 位小数，使用四舍五入。
明确提供左右镜像、上下镜像、180° 旋转；默认不变换。角度按同一几何规则转换。
极性件真实零度方向仍需依据器件库和装夹方向核对。

默认 YGX 结构来自已验证 YSM20 样例；可以导入目标机型已可用的 YGX 作为结构模板。
原点字段默认 `OriginX=-板宽, OriginY=0`，与本项目既有 YSUP 转换样例一致；可在高级设置中明确覆盖。
MARK 原生尺寸编辑支持圆形和矩形；其他形状可通过 YGX 模板保留其完整 XML。未知形状枚举不自动猜测。
Light/Filter/Surface 等字段使用 YSUP 原始参数值；各机型有效范围尚未全面验证。

## REST API

访问 `http://127.0.0.1:8765/docs` 查看实际接口。主要能力：

| 功能 | HTTP 接口 |
| --- | --- |
| 创建/读取项目 | `POST /api/projects`、`GET /api/projects/{id}` |
| 板/MARK | `PUT /api/projects/{id}/board`、`PUT /api/projects/{id}/marks` |
| 拼板/辅助标记 | `GET /api/assembly-defaults`、`PUT /api/projects/{id}/assembly` |
| 表格导入/整理 | `POST/PUT /api/projects/{id}/tables/{bom或cad}` |
| 导入/查库 | `POST/GET /api/projects/{id}/library` |
| 库编辑/复制 | `PUT /api/projects/{id}/library/{part_id}`、`POST .../duplicate` |
| 物料确认 | `PUT /api/projects/{id}/matches/{group_id}` |
| 合并校验/生成 | `POST .../analyze`、`POST .../export` |
| 完整快照 | `GET .../save`、`POST /api/projects/load` |

列索引、稳定原始行号均从 0 开始。`header_row=-1` 表示没有表头。
每个项目更改立即保存；SQLite 事务防止 UI/MCP 同时写入时丢失更改。
下载完整项目后可恢复原表、整理规则、MARK、库参数、匹配和导出历史；导出历史仅保留原路径/摘要，恢复后需重新生成才能下载文件。
错误返回 `errors` 数组，含 `code/message` 及适用的行号/物料 id。
导出保存板信息、来源文件 SHA256、整理规则和物料关联至 `manifest.json`。

## MCP / DSH

实际 MCP Server 已实现，支持标准 stdio 和 Streamable HTTP。
stdio：DSH 启动 `run_mcp.py` 即可；无需先启动网页服务。
运行 `python tools/generate_mcp_config.py` 可生成针对本机路径的 `mcp_config.local.json`。
其中 `mcpServers` 是通用客户端配置示例；尚未在用户的 DSH 中实测其配置界面/字段。

工具包括 create/list/get/rename_project、set_board、get_mark_defaults、set_marks、import_mark_templates、
import/configure_table、import/list/get/update/duplicate_library、match_part、import_ygx_template、
analyze_project、export_ygx、save/load_project。
[REPO] 人工确认关联库另有 `confirm_library_associations`、`query_library_associations`、
`list_library_associations`、`apply_library_associations`、`revoke_library_association`；
安装与确认历史迁移见 [安装与接入](DEPLOYMENT.md)。
[REPO] 线体优化已提供 `list_optimization_lines`、`start_line_optimization`、
`get_line_optimization`。配置 `YAMAHA_YSUP_ROOT` 后，读取该安装目录已配置线体与已保存 `.ygs`；
每个任务复制到 `YAMAHA_OPTIMIZER_WORK`（默认数据目录的 `optimization`）运行。
仅 `status=succeeded` 且 `mounts_identical=true` 时交付分机文件；优化成功仍需工艺与机台确认。
拼板配置使用 `get_assembly_defaults` 和 `set_assembly`。默认模板返回完整 XML，可编辑其参数后保存。

`set_assembly` 的 settings 与 REST body 相同：

```json
{
  "repeats": [{"x": 0, "y": 0, "rotation": 0}, {"x": 120, "y": 0, "rotation": 0}],
  "profiles": [],
  "block_fid": [],
  "local_fids": [],
  "bad_marks": {"local": []},
  "assignments": {}
}
```

profiles 项为 `{id,xml}`；辅助点为 `{x,y,profile}`。
local_fids 项为 `{id,type,marks,comment}`，type 为 local/point/four_main/four_secondary。
bad_marks 的 board/block 为辅助点对象，local 为带 id 的辅助点列表。
assignments 为 `{ "C1": {"fid":1,"bad":1} }`；0 表示不关联，局部编号需从 1 连续递增。
整个 assembly 配置一次替换并保存；缺省项清空，旧导入模板的局部/坏板/拼板数据不会混入新输出。

HTTP：`python run_mcp.py --transport streamable-http --port 8766`，端点 `http://127.0.0.1:8766/mcp`。
服务绑定本机回环地址。MCP 读取客户端指定的本地文件、保存指定项目文件；软件自身不向云端发送文件。
界面与 MCP 使用同一个 `YAMAHA_BUILDER_DATA` 目录，默认本项目的 `data`。

[REPO] 确认关联默认保存在该目录的 `confirmed_associations.sqlite3`，独立于项目文件。
项目目录按运行隔离时，必须用 `YAMAHA_ASSOCIATIONS_DB` 或 spec 的 `mcp.association_db`
指向同一个共享文件，才能跨项目查询；备份该 SQLite 文件可保留确认历史。

## 验证与边界

[REPO] 分发包校验：`python tools/check_package.py`；包内回归：`python -X utf8 -m unittest discover -s tests -v`。包内不附带客户夹具。包内优化器测试使用合成数据，不启动真实 YSUP。
[REPO] 本机开发目录已有真实 stdio/HTTP MCP、确认关联库和 Line1 优化验收记录；这些记录不随源码上传。
[UNKNOWN] 原生设备约束、实际机器试贴、视觉参数和生产原点的现场验证尚未完成。成功导出或优化只证明离线链路，不证明生产工艺可用。
