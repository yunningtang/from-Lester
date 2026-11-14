"""确认对话框：把预检结果（Plan）原样告诉用户。所有删除前都必须经过这里。"""
from __future__ import annotations

from tkinter import messagebox

from core.cleaner import Plan, TrashReport
from core.utils import human_size


def _short(text: str, n: int = 70) -> str:
    return text if len(text) <= n else text[: n // 2 - 1] + "…" + text[-(n // 2):]


def ask(plan: Plan, what: str) -> bool:
    """what：这次要移走的是什么，比如“11 项缓存”。返回用户是否确定。"""
    if not plan.go:
        reasons = "\n".join(f"· {_short(p, 50)}\n  {why}" for p, why in plan.refused[:8])
        messagebox.showinfo("没有可以移动的", f"这些都不能移到回收站：\n\n{reasons}")
        return False
    lines = [f"把 {what}移到回收站，共 {human_size(plan.total)}。", ""]
    lines += [f"· {_short(e.path)}" for e in plan.go[:6]]
    if len(plan.go) > 6:
        lines.append(f"……共 {len(plan.go)} 项")
    if plan.refused:
        lines += ["", f"另有 {len(plan.refused)} 项不会动："]
        lines += [f"· {_short(p, 50)}：{why}" for p, why in plan.refused[:4]]
    if plan.warnings:
        lines += [""] + plan.warnings
    lines += ["", "可以从回收站找回。确定吗？"]
    return messagebox.askyesno("确认移到回收站", "\n".join(lines), icon="warning", default="no")


def summary(rep: TrashReport) -> str:
    msg = f"已把 {len(rep.moved)} 项移到回收站，共 {human_size(rep.trashed)}。清空回收站后，这些空间才会空出来。"
    if rep.failed:
        msg += f"\n{len(rep.failed)} 项没有移动（正在使用或有变化），详见清理记录。"
    return msg
