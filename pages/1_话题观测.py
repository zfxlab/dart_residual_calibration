"""Extensible topic observation page; importing this page does not import ROS."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from page_state import retain_page_state
from topic_capture import Capture
from topic_data import FIELDS, summarize, valid_value

st.set_page_config(page_title="话题观测", page_icon="📈", layout="wide")
retain_page_state("observation")
st.title("话题观测")
st.caption("实时采集 → 时间曲线 → 选段统计 → 导出；当前支持 StereoTarget 消息。")
st.info(
    "启动网页前请 source ROS 和工作区 setup.bash。采集使用系统 Python 和 Best Effort QoS；"
    "回放 bag 时也可使用。距离与角度相对消息的 frame_id，不能直接作为 launcher_frame 标定记录。"
)

# No form: every committed edit reaches session state before page navigation.
topic = st.text_input("话题", key="observation_topic", placeholder="例如 /camera/stereo_target")
mode = st.radio("工作模式", ["实时预览", "定时采集"], horizontal=True, key="observation_mode")
preview = mode == "实时预览"
if not preview:
    left, right = st.columns(2)
    duration = left.number_input("采集时长（秒）", 1, 3600, value=None, key="observation_duration")
    limit = right.number_input(
        "样本上限（达到后停止）", 100, 100000, value=None, step=100, key="observation_limit"
    )
else:
    # Also retain settings when hidden by a mode change on this same page.
    for key in ("observation_duration", "observation_limit"):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
start = st.button("开始实时预览" if preview else "开始新采集")
resource_key = "topic_preview" if preview else "topic_capture"

if start:
    previous = st.session_state.get(resource_key)
    if previous and previous.running:
        st.warning("请先停止当前订阅。")
    elif not topic.startswith("/") or any(char.isspace() for char in topic):
        st.error("请输入完整话题路径，例如 /camera/stereo_target。")
    elif not preview and (duration is None or limit is None):
        st.error("请填写采集时长和样本上限。")
    else:
        try:
            st.session_state[resource_key] = (
                Capture(topic, 0, 5000, preview=True)
                if preview
                else Capture(topic, duration, limit)
            )
            st.session_state.pop("observation_range", None)
        except OSError as error:
            st.error(f"无法启动 ROS 采集进程：{error}")

st.caption(
    "实时预览仅保留最近 5000 条消息的内存缓存，不创建采集结果，不影响已有采集。停止预览后断开订阅。"
    if preview
    else "开始新采集会替换旧采集数据，请先导出需要保留的结果。"
)
fields = st.multiselect("观测字段", list(FIELDS), key="observation_fields")
if not fields:
    st.info("请选择需要绘制的字段，例如 distance、yaw。")
window = st.number_input(
    "实时显示及统计最近秒数（留空或 0 表示全部缓存）",
    0,
    3600,
    value=None,
    key="observation_window",
)


@st.fragment(run_every=1)
def observation():
    capture = st.session_state.get(resource_key)
    if capture is None:
        st.info("尚未开始实时预览。" if preview else "尚未开始采集。")
        return
    left, right = st.columns(2)
    if left.button("停止预览" if preview else "停止采集", disabled=not capture.running):
        capture.stop()
    if right.button("清空数据", disabled=capture.running):
        st.session_state.pop(resource_key, None)
        st.session_state.pop("observation_range", None)
        st.rerun()
    samples, logs, last_received = capture.snapshot()
    running = capture.running
    label = ("实时预览中" if preview else "正在采集") if running else "已停止"
    st.write(f"{label} · {capture.topic} · {len(samples)} 条缓存消息")
    if not preview and len(samples) >= capture.limit:
        st.info("已达到样本上限，自动停止。")
    if last_received is not None:
        st.caption(f"最后一条消息距今 {time.monotonic() - last_received:.1f} 秒")
    if not running and capture.process.returncode and not capture.stopped:
        st.error("采集进程失败。请检查下方日志中的 ROS 环境、消息版本或话题错误。")
    if logs:
        with st.expander("采集日志", expanded=not samples):
            st.code("\n".join(logs))
    if not samples:
        st.warning("尚未收到消息。请确认发布节点运行、ROS_DOMAIN_ID 一致且话题名称正确。")
        return

    segments = sorted({sample["segment"] for sample in samples})
    segment_key = f"observation_segment_{capture.started}"
    if st.session_state.get(segment_key) not in segments:
        st.session_state[segment_key] = segments[-1]
    segment = st.selectbox(
        "数据段（坐标系变化或 ROS 时间回退时分段）",
        segments,
        key=segment_key,
    )
    segment_samples = [sample for sample in samples if sample["segment"] == segment]
    st.caption(f"参考系：{segment_samples[0]['frame_id']}；yaw 向右为正，无飞镖补偿。")
    selected = segment_samples
    if running or preview:
        if window:
            cutoff = time.monotonic() - capture.started - window
            selected = [sample for sample in selected if sample["elapsed_s"] >= cutoff]
    else:
        lower, upper = selected[0]["elapsed_s"], selected[-1]["elapsed_s"]
        if upper > lower:
            interval = st.slider(
                "统计时间段（接收时间，秒）",
                lower,
                upper,
                (lower, upper),
                key=f"observation_range_{segment}_{capture.started}",
            )
            selected = [s for s in selected if interval[0] <= s["elapsed_s"] <= interval[1]]

    summary = summarize(selected, fields)
    st.caption(
        "均值按消息等权计算，仅统计 status=VALID 且该字段为有限数值的样本；"
        "无效帧显示为断点。标准差为样本标准差（至少 2 个有效样本）。yaw 单位为弧度。"
    )
    if summary:
        st.dataframe(
            pd.DataFrame(summary),
            hide_index=True,
            width="stretch",
            column_config={
                "field": "字段",
                "unit": "单位",
                "total": "总样本数",
                "valid": "有效样本数",
                "valid_ratio": st.column_config.NumberColumn("有效率（0–1）", format="%.3f"),
                "mean": st.column_config.NumberColumn("平均值", format="%.6f"),
                "std_sample": st.column_config.NumberColumn("样本标准差", format="%.6f"),
                "min": st.column_config.NumberColumn("最小值", format="%.6f"),
                "max": st.column_config.NumberColumn("最大值", format="%.6f"),
            },
        )
    if selected and not any(s["status"] == 1 for s in selected):
        st.warning("选定时间段有消息，但没有 VALID 测量。")
    for stats in summary:
        field = stats["field"]
        figure = go.Figure(
            go.Scatter(
                x=[sample["elapsed_s"] for sample in selected],
                y=[sample[field] if valid_value(sample, field) else None for sample in selected],
                mode="lines+markers",
                marker={"size": 3},
                connectgaps=False,
                name=field,
            )
        )
        if stats["mean"] is not None:
            figure.add_hline(
                y=stats["mean"], line_dash="dash", annotation_text=f"均值 {stats['mean']:.6f}"
            )
        figure.update_layout(
            title=field,
            xaxis_title="接收时间 / s",
            yaxis_title=stats["unit"],
            height=300,
            uirevision=f"{capture.started}_{segment}_{field}",
        )
        st.plotly_chart(figure, width="stretch", key=f"curve_{field}")
    if preview and samples:
        latest = samples[-1]
        st.write(
            {
                "最新 status": latest["status"],
                **{
                    field: latest[field] if valid_value(latest, field) else None for field in fields
                },
            }
        )
    st.caption("图表缩放仅改变视图；统计范围由时间范围控件决定。定时采集停止后可导出。")
    if not running and not preview:
        st.download_button(
            "下载全部原始数据 CSV",
            pd.DataFrame(samples).to_csv(index=False).encode("utf-8-sig"),
            "stereo_observations.csv",
            "text/csv",
        )
        st.download_button(
            "下载选段数据 CSV",
            pd.DataFrame(selected).to_csv(index=False).encode("utf-8-sig"),
            "stereo_selection.csv",
            "text/csv",
        )
        report = {
            "topic": capture.topic,
            "segment": segment,
            "frame_id": segment_samples[0]["frame_id"],
            "receive_time_range_s": [selected[0]["elapsed_s"], selected[-1]["elapsed_s"]]
            if selected
            else None,
            "method": "message-weighted mean; status=1 and finite per field; sample std ddof=1",
            "statistics": summary,
        }
        st.download_button(
            "下载统计 JSON",
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
            "stereo_statistics.json",
            "application/json",
        )


observation()
