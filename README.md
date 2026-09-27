# ICT5 · 政府采购智能数据分析检索平台

面向行业数据的智能实体挖掘与关系建模（中国电子杯 第三届高校ICT产教融合创新大赛 · 赛题五 · 后端实现）。

## 功能

- **任务一 · 实体自动化提取**：公告 HTML + 附件包（zip/PDF/Word/Excel/嵌套压缩）自动解析，抽取 7 字段（产品服务名称/品目/品牌/规格型号/单价/数量/总价），规则引擎为主、可选接入 Qwen/DeepSeek 大模型（支持长文本分块抽取+重试）。
- **任务二 · 关系建模**：采购单位—中标供应商—投标参与方关系建模与 5 大业务场景查询。
- **任务三 · 分析检索平台**：数据集批量上传自动入库、标的物全字段检索筛选、统计概览、知识图谱数据导出；内置可视化页面（ECharts 本地化，离线可演示）。

## 快速开始

```bash
cd backend
pip install -r requirements.txt
python -m app.cli ingest ../sample_dataset   # 导入官方样例
python -m app.cli serve                      # 启动服务 (默认 0.0.0.0:8000)
```

打开 `http://localhost:8000/platform` 体验平台，`/docs` 查看接口文档。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `backend/app` | 后端源码：解析器 / 抽取流水线 / LLM 引擎 / 数据库 / 关系查询 / API 路由 / 内置静态平台 |
| `backend/data/dsh.db` | 已生成的全量数据库（1032 篇公告 / 6371 标的物 / 8698 主体 / 10527 参与关系） |
| `backend/tests` | 冒烟测试（30 断言，`python tests/smoke_test.py`） |
| `backend/tools` | 全量验证/统计工具 |
| `sample_dataset/` | 官方样例数据（1 篇公告 html + 附件 zip） |
| `input/` | 赛题题目与验证样例 |

详细说明见 [backend/README.md](backend/README.md)。
