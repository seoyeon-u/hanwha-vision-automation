"""Plotly figures driven by the dashboard's measured results."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

BLUE = "#2563CB"
PALETTE = ["#2356BE", "#3779DD", "#5EA5E7", "#137F95", "#26957C", "#685DC0",
           "#B16DC8", "#C97C36", "#A84175", "#53748F", "#D3A132"]


def object_figures(counts: dict[str, int]) -> tuple[go.Figure, go.Figure]:
    rows = sorted(counts.items(), key=lambda item: -item[1])
    labels, values = map(list, zip(*rows)) if rows else ([], [])
    total = sum(values)
    bar = go.Figure(go.Bar(
        x=labels, y=values, text=values, textposition="outside", marker_color=BLUE,
        customdata=[value / total if total else 0 for value in values],
        hovertemplate="%{x}<br>객체 %{y:,}개<br>비율 %{customdata:.1%}<extra></extra>",
    ))
    bar.update_xaxes(title="객체 클래스", categoryorder="array", categoryarray=labels, tickangle=-30)
    bar.update_yaxes(title="객체 수", rangemode="tozero")
    nonzero = [(label, value) for label, value in rows if value]
    pie = go.Figure(go.Pie(
        labels=[label for label, _ in nonzero], values=[value for _, value in nonzero], hole=0.65,
        marker_colors=PALETTE, sort=False, textinfo="percent",
        hovertemplate="%{label}<br>객체 %{value:,}개<br>비율 %{percent}<extra></extra>",
    ))
    pie.add_annotation(text=f"<b>{total:,}</b><br>객체", showarrow=False, x=0.5, y=0.5, font_size=17)
    for figure in (bar, pie):
        figure.update_layout(height=360, margin=dict(t=20, b=24, l=24, r=24), template="plotly_white")
    return bar, pie


def folder_figure(frame: pd.DataFrame, metric: str) -> go.Figure:
    comparison = frame.sort_values(metric, ascending=False, kind="stable").head(20)
    figure = px.bar(comparison.iloc[::-1], x=metric, y="폴더", orientation="h", text=metric,
                    color_discrete_sequence=[BLUE], template="plotly_white")
    figure.update_layout(height=max(240, 45 * len(comparison) + 70), margin=dict(t=12, b=30, l=15, r=32),
                         yaxis_title=None)
    figure.update_traces(textposition="outside", cliponaxis=False)
    return figure
