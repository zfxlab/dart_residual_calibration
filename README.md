# Data Workbench · 数据实验工作台

一个本地运行的通用实验数据工具，提供数据导入、编辑、可视化、ROS 2 实时采集、派生列运算和函数拟合。界面中的三个工作区完全分离：

- `#/explore`：数据探索、筛选、表格编辑、列运算和实验汇总记录。
- `#/fit`：变量表达式、模型配置、训练/验证、函数模板和模型比较。
- `#/capture`：ROS 2 话题连接、实时曲线和采集结果保存。

图表使用 SVG 渲染，不依赖 WebGL，可在 VS Code 内置网页中使用。

## 启动

首次安装：

```bash
cd tools/residual_calibration
uv venv .venv --python python3.12
uv pip install --python .venv/bin/python -r requirements-uv.lock
```

从仓库任意目录启动：

```bash
bash tools/residual_calibration/run.sh
# 自定义端口
bash tools/residual_calibration/run.sh --port 8502
```

默认访问 <http://127.0.0.1:8501>。服务仅监听本机，前端资源由本地服务提供，不需要 Node.js 或前端构建工具。

## 项目与数据集

- 点击侧栏项目名可以命名项目。浏览器自动保存项目名、数据集、派生列、拟合配置和函数模板。
- “保存项目 JSON”使用项目名作为文件名；旧项目 JSON 没有名称时，导入到空工作区会采用 JSON 文件名。
- CSV 继续使用数据集名称作为文件名，导出当前筛选或选区的数据。
- 每个数据集右侧的删除按钮会先确认。删除后可在本次页面会话中撤销最近 10 次删除；刷新页面后撤销栈不保留。
- 导入项目采用追加语义：空工作区采用导入项目名；已有数据时保留当前项目名并追加数据集和模板。
- 数据保存在当前浏览器地址的 `localStorage`。建议定期下载项目 JSON；浏览器存储清理后只能从已下载文件恢复。

项目 JSON 版本仍为 `version: 1`，旧版未命名的新工作台 JSON 可继续导入。

## 数据探索与列运算

支持 CSV 导入、手工建表、散点图、折线图、直方图、箱线图、矩形选区、范围筛选和字段等值筛选。数据记录显示在图表上方。单击单元格即可原位编辑，Enter 或离开单元格保存，Esc 取消；派生列只读。每行可删除，列标题旁可删除字段；被派生列依赖的字段需先解除依赖，至少保留一个字段。折线按 X 升序连接，相同 X 保持记录顺序，原始表格不排序。

派生列表达式示例：

```text
[reference] - [measured]
([left] + [right]) / 2
[yaw_rad] * 180 / pi
```

支持 `+ - * / **`、括号和 `sin/cos/tan/exp/log/ln/sqrt/abs`。表达式由受限 AST 解释器计算，不使用 `eval` 或 `exec`。源记录修改后按依赖顺序重算；缺失值、除零和定义域错误产生空值；循环依赖和未知字段会被拒绝。

“将选区均值保存为记录”会生成独立实验汇总数据集，记录各数值字段的均值、有效数和样本标准差。

## 函数拟合

内置常数、线性、二次、三次、指数、对数、幂函数、高斯、正弦和饱和模型，也支持自定义表达式，例如：

```text
a * exp(-b*x) + c
```

可配置参数初值、上下界、固定参数、权重字段、普通最小二乘或 Huber/Soft-L1 稳健损失。X/Y 直接从当前数据集的原始列或派生列中选择；列运算统一在数据探索页完成。验证集可按原始行序留出，或按批次字段整组留出。

普通最小二乘在条件允许时给出 95% 参数置信区间；稳健损失、边界参数或参数不可识别时不提供区间。模型 JSON 包含表达式、参数、区间、派生列、数据划分和来源指纹。

## ROS 2 实时采集

采集页可填写话题和消息类型。嵌套标量展开为点分隔字段，数组暂不采集；默认使用 Sensor Data QoS。停止后点击“保存为数据集”，即可进入通用探索与拟合流程。

启动服务前需在同一终端加载 ROS 和消息工作区。采集子进程默认使用 `/usr/bin/python3`，可通过 `DART_ROS_PYTHON` 指定。

## 目录结构

```text
residual_calibration/
├── backend/
│   ├── analysis/       # 表达式与拟合
│   ├── capture/        # ROS 数据解析、任务管理和订阅进程
│   ├── server.py       # HTTP/API 服务
│   └── __main__.py     # python -m backend
├── frontend/
│   ├── css/
│   ├── js/
│   └── index.html
├── tests/
├── requirements-uv.in
├── requirements-uv.lock
└── run.sh
```

原 Streamlit 残差标定工具及其兼容代码已删除，不再提供旧入口。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
RUN_BROWSER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_workbench_browser.py' -v
.venv/bin/python -m backend --help
```

真实 ROS 发布/订阅测试需要加载 ROS 环境后显式启用：

```bash
RUN_ROS_CAPTURE_TESTS=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_ros_capture.py' -v
```

单个数据集最多 100000 行，上传文件最大 32 MB。散点和折线显示会按区间极值降采样至约 2000 点，筛选、统计和拟合仍使用完整数据。
