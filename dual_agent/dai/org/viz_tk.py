"""Tkinter 組織圖譜視窗（Phase V1：唯讀）。"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

from dual_agent.dai.org.layout import NODE_HEIGHT, NODE_WIDTH, OrgLayoutResult, layout_org_hierarchy
from dual_agent.dai.org.schemas import OrgGraph, org_graph_to_dict
from dual_agent.dai.org.store import get_default_org_path, load_org_graph


class OrgGraphWindow:
    """組織匯報線樹狀圖（唯讀）。"""

    def __init__(self, master: tk.Misc) -> None:
        self._master = master
        self._win = tk.Toplevel(master)
        self._win.title("組織圖譜")
        self._win.geometry("900x620")
        self._win.minsize(640, 480)

        self._graph: OrgGraph | None = None
        self._layout: OrgLayoutResult | None = None
        self._selected_id: str | None = None
        self._node_items: dict[str, int] = {}
        self._edge_items: list[int] = []

        self._build_ui()
        self._reload_graph()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self._win, padding=6)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="重新整理", command=self._reload_graph).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="匯出 JSON", command=self._export_json).pack(side=tk.LEFT, padx=(8, 0))

        self._status_var = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self._status_var, foreground="#555").pack(
            side=tk.LEFT, padx=(16, 0)
        )

        body = ttk.Frame(self._win, padding=(6, 0, 6, 6))
        body.pack(fill=tk.BOTH, expand=True)

        canvas_frm = ttk.Frame(body)
        canvas_frm.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(canvas_frm, background="#f8f9fb", highlightthickness=0)
        x_scroll = ttk.Scrollbar(canvas_frm, orient=tk.HORIZONTAL, command=self._canvas.xview)
        y_scroll = ttk.Scrollbar(canvas_frm, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        canvas_frm.rowconfigure(0, weight=1)
        canvas_frm.columnconfigure(0, weight=1)

        self._canvas.bind("<Button-1>", self._on_canvas_click)

        detail_frm = ttk.LabelFrame(body, text="詳情", padding=8, width=220)
        detail_frm.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        detail_frm.pack_propagate(False)

        self._detail = scrolledtext.ScrolledText(
            detail_frm, width=26, height=24, wrap=tk.WORD, state=tk.DISABLED, font=("Segoe UI", 10)
        )
        self._detail.pack(fill=tk.BOTH, expand=True)
        self._set_detail_text("點選左側節點以查看詳情。")

    def _reload_graph(self) -> None:
        try:
            self._graph = load_org_graph()
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            self._graph = None
            self._layout = None
            self._status_var.set(str(exc))
            self._clear_canvas()
            self._set_detail_text(f"無法載入組織圖譜：\n{exc}")
            return

        try:
            self._layout = layout_org_hierarchy(self._graph)
        except ValueError as exc:
            self._layout = None
            self._status_var.set(str(exc))
            self._clear_canvas()
            self._set_detail_text(str(exc))
            return

        path = get_default_org_path()
        n_emp = len(self._graph.employees)
        self._status_var.set(f"已載入 {n_emp} 人 · {path.name if path else '（未知路徑）'}")
        self._render()

    def _clear_canvas(self) -> None:
        self._canvas.delete("all")
        self._node_items.clear()
        self._edge_items.clear()

    def _render(self) -> None:
        if not self._graph or not self._layout:
            return
        self._clear_canvas()
        graph = self._graph
        layout = self._layout

        self._canvas.configure(
            scrollregion=(0, 0, int(layout.canvas_width), int(layout.canvas_height))
        )

        for edge in graph.edges:
            if edge.type != "reports_to":
                continue
            mgr = layout.nodes.get(edge.to_id)
            rep = layout.nodes.get(edge.from_id)
            if not mgr or not rep:
                continue
            line_id = self._canvas.create_line(
                mgr.center_x,
                mgr.y + NODE_HEIGHT,
                rep.center_x,
                rep.y,
                fill="#6b7280",
                width=2,
                arrow=tk.LAST,
            )
            self._edge_items.append(line_id)

        for emp_id, node in layout.nodes.items():
            emp = graph.employees.get(emp_id)
            if not emp:
                continue
            fill = "#dbeafe" if emp_id == self._selected_id else "#ffffff"
            outline = "#2563eb" if emp_id == self._selected_id else "#94a3b8"
            rect_id = self._canvas.create_rectangle(
                node.x,
                node.y,
                node.x + NODE_WIDTH,
                node.y + NODE_HEIGHT,
                fill=fill,
                outline=outline,
                width=2,
                tags=("node", emp_id),
            )
            name_id = self._canvas.create_text(
                node.center_x,
                node.y + 18,
                text=emp.name,
                font=("Segoe UI", 10, "bold"),
                fill="#111827",
                tags=("node", emp_id),
            )
            title = emp.title or "—"
            title_id = self._canvas.create_text(
                node.center_x,
                node.y + 36,
                text=title[:14] + ("…" if len(title) > 14 else ""),
                font=("Segoe UI", 9),
                fill="#4b5563",
                tags=("node", emp_id),
            )
            self._node_items[emp_id] = rect_id
            self._canvas.tag_bind(rect_id, "<Enter>", lambda _e, eid=emp_id: self._canvas.config(cursor="hand2"))
            self._canvas.tag_bind(rect_id, "<Leave>", lambda _e: self._canvas.config(cursor=""))
            for tid in (name_id, title_id):
                self._canvas.tag_bind(tid, "<Button-1>", lambda e, eid=emp_id: self._select_node(eid))

    def _on_canvas_click(self, event: tk.Event[Any]) -> None:
        if not self._layout:
            return
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        for emp_id, node in self._layout.nodes.items():
            if node.contains(cx, cy):
                self._select_node(emp_id)
                return

    def _select_node(self, employee_id: str) -> None:
        self._selected_id = employee_id
        self._render()
        self._show_employee_detail(employee_id)

    def _show_employee_detail(self, employee_id: str) -> None:
        if not self._graph:
            return
        emp = self._graph.employees.get(employee_id)
        if not emp:
            return
        mgr_id = self._graph.get_manager_id(employee_id)
        mgr_name = ""
        if mgr_id and mgr_id in self._graph.employees:
            mgr_name = self._graph.employees[mgr_id].name
        reports = self._graph.list_direct_reports(employee_id)
        report_lines = []
        for rid in reports:
            r = self._graph.employees.get(rid)
            if r:
                report_lines.append(f"  · {r.name}（{r.title or '—'}）")
        dept = self._graph.department_name(emp.department_id) if emp.department_id else "—"
        lines = [
            f"姓名：{emp.name}",
            f"職稱：{emp.title or '—'}",
            f"部門：{dept}",
            f"員工 ID：{emp.id}",
            f"匯報給：{mgr_name or '（無／最高層）'}",
        ]
        if report_lines:
            lines.append("直屬下屬：")
            lines.extend(report_lines)
        else:
            lines.append("直屬下屬：（無）")
        self._set_detail_text("\n".join(lines))

    def _set_detail_text(self, text: str) -> None:
        self._detail.configure(state=tk.NORMAL)
        self._detail.delete("1.0", tk.END)
        self._detail.insert(tk.END, text)
        self._detail.configure(state=tk.DISABLED)

    def _export_json(self) -> None:
        if not self._graph:
            messagebox.showwarning("組織圖譜", "目前無可匯出的資料。")
            return
        export_win = tk.Toplevel(self._win)
        export_win.title("匯出 JSON")
        export_win.geometry("520x400")
        txt = scrolledtext.ScrolledText(export_win, wrap=tk.WORD, font=("Consolas", 10))
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        txt.insert(tk.END, json.dumps(org_graph_to_dict(self._graph), ensure_ascii=False, indent=2))
        txt.configure(state=tk.DISABLED)


def open_org_graph_window(master: tk.Misc) -> OrgGraphWindow:
    return OrgGraphWindow(master)
