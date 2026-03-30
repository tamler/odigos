"""Spreadsheet tool -- create, read, and modify Excel files.

Uses openpyxl to work with .xlsx files. The agent can maintain
persistent spreadsheets (budgets, trackers, logs) that accumulate
data over time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from odigos.storage import FILES_DIR
from odigos.tools.base import BaseTool, ToolContract, ToolResult

logger = logging.getLogger(__name__)

try:
    import openpyxl
    from openpyxl.utils import get_column_letter
    _XLSX_AVAILABLE = True
except ImportError:
    _XLSX_AVAILABLE = False


def _create_workbook(filepath: str, sheet_name: str, headers: list[str], rows: list[list]) -> dict:
    """Create a new Excel workbook with headers and optional initial data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    # Write headers with bold formatting
    from openpyxl.styles import Font
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    # Write data rows
    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-size columns
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = max(12, len(str(headers[col - 1])) + 4)

    wb.save(filepath)
    return {"rows": len(rows), "columns": len(headers), "sheet": sheet_name}


def _read_workbook(filepath: str, sheet_name: str | None = None, limit: int = 50) -> dict:
    """Read data from an Excel workbook."""
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active

    rows = []
    headers = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(c) if c is not None else "" for c in row]
        elif i <= limit:
            rows.append([c if c is not None else "" for c in row])

    wb.close()
    return {
        "sheet": ws.title,
        "sheets": wb.sheetnames,
        "headers": headers,
        "rows": rows,
        "total_rows": ws.max_row - 1 if ws.max_row else 0,
    }


def _append_rows(filepath: str, rows: list[list], sheet_name: str | None = None) -> dict:
    """Append rows to an existing Excel workbook."""
    wb = openpyxl.load_workbook(filepath)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active

    start_row = ws.max_row + 1
    for row_idx, row_data in enumerate(rows):
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=start_row + row_idx, column=col_idx, value=value)

    wb.save(filepath)
    return {"appended": len(rows), "total_rows": ws.max_row - 1, "sheet": ws.title}


def _update_cell(filepath: str, cell_ref: str, value, sheet_name: str | None = None) -> dict:
    """Update a specific cell in an Excel workbook."""
    wb = openpyxl.load_workbook(filepath)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active

    ws[cell_ref] = value
    wb.save(filepath)
    return {"cell": cell_ref, "value": value, "sheet": ws.title}


def _add_formula(filepath: str, cell_ref: str, formula: str, sheet_name: str | None = None) -> dict:
    """Add a formula to a cell."""
    wb = openpyxl.load_workbook(filepath)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active

    ws[cell_ref] = formula
    wb.save(filepath)
    return {"cell": cell_ref, "formula": formula, "sheet": ws.title}


class SpreadsheetTool(BaseTool):
    """Create, read, and modify Excel spreadsheets."""

    name = "spreadsheet"
    category = "create"
    description = (
        "Create, read, append to, and modify Excel (.xlsx) spreadsheets. "
        "Use for budgets, expense tracking, data tables, logs, or any structured data "
        "that needs to persist and accumulate over time. "
        "Do not use for one-off data exports — use create_artifact with CSV instead."
    )
    contract = ToolContract(timeout_seconds=30)
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "read", "append", "update_cell", "add_formula"],
                "description": "Operation to perform on the spreadsheet.",
            },
            "filename": {
                "type": "string",
                "description": "Spreadsheet filename (e.g. 'budget.xlsx'). Must end in .xlsx.",
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet name (optional, defaults to active sheet).",
            },
            "headers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column headers for create action.",
            },
            "rows": {
                "type": "array",
                "items": {"type": "array"},
                "description": "Data rows for create or append. Each row is an array of values.",
            },
            "cell": {
                "type": "string",
                "description": "Cell reference for update_cell or add_formula (e.g. 'A1', 'C5').",
            },
            "value": {
                "description": "Value for update_cell action.",
            },
            "formula": {
                "type": "string",
                "description": "Excel formula for add_formula (e.g. '=SUM(B2:B100)').",
            },
            "limit": {
                "type": "integer",
                "description": "Max rows to return for read action (default 50).",
            },
        },
        "required": ["action", "filename"],
    }

    def __init__(self, db=None):
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        if not _XLSX_AVAILABLE:
            return ToolResult(success=False, data="", error="openpyxl not installed")

        action = params.get("action", "")
        filename = params.get("filename", "")
        conversation_id = params.pop("_conversation_id", None)
        params.pop("_goal_id", None)

        if not filename.endswith(".xlsx"):
            filename += ".xlsx"

        safe_name = Path(filename).name
        filepath = str(FILES_DIR / safe_name)

        try:
            if action == "create":
                headers = params.get("headers", [])
                rows = params.get("rows", [])
                if not headers:
                    return ToolResult(success=False, data="", error="headers required for create")
                sheet = params.get("sheet_name", "Sheet1")
                result = await asyncio.to_thread(_create_workbook, filepath, sheet, headers, rows)

                # Register as artifact
                if self._db:
                    from datetime import datetime, timezone
                    import secrets
                    artifact_id = secrets.token_hex(8)
                    now = datetime.now(timezone.utc).isoformat()
                    file_size = os.path.getsize(filepath)
                    await self._db.execute(
                        "INSERT OR REPLACE INTO artifacts "
                        "(id, conversation_id, filename, content_type, file_size, file_path, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (artifact_id, conversation_id, safe_name,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         file_size, filepath, now),
                    )

                return ToolResult(
                    success=True,
                    data=f"Created {safe_name}: {result['columns']} columns, {result['rows']} rows.",
                )

            elif action == "read":
                if not os.path.exists(filepath):
                    return ToolResult(success=False, data="", error=f"File not found: {safe_name}")
                limit = params.get("limit", 50)
                sheet = params.get("sheet_name")
                result = await asyncio.to_thread(_read_workbook, filepath, sheet, limit)

                lines = [f"## {safe_name} ({result['sheet']})"]
                lines.append(f"Sheets: {', '.join(result['sheets'])}")
                lines.append(f"Total rows: {result['total_rows']}\n")

                # Format as markdown table
                if result["headers"]:
                    lines.append("| " + " | ".join(result["headers"]) + " |")
                    lines.append("| " + " | ".join(["---"] * len(result["headers"])) + " |")
                    for row in result["rows"]:
                        lines.append("| " + " | ".join(str(c) for c in row) + " |")

                return ToolResult(success=True, data="\n".join(lines))

            elif action == "append":
                if not os.path.exists(filepath):
                    return ToolResult(success=False, data="", error=f"File not found: {safe_name}")
                rows = params.get("rows", [])
                if not rows:
                    return ToolResult(success=False, data="", error="rows required for append")
                sheet = params.get("sheet_name")
                result = await asyncio.to_thread(_append_rows, filepath, rows, sheet)

                # Update artifact file_size
                if self._db:
                    file_size = os.path.getsize(filepath)
                    await self._db.execute(
                        "UPDATE artifacts SET file_size = ? WHERE filename = ?",
                        (file_size, safe_name),
                    )

                return ToolResult(
                    success=True,
                    data=f"Appended {result['appended']} rows to {safe_name}. Total: {result['total_rows']} rows.",
                )

            elif action == "update_cell":
                if not os.path.exists(filepath):
                    return ToolResult(success=False, data="", error=f"File not found: {safe_name}")
                cell = params.get("cell", "")
                value = params.get("value")
                if not cell:
                    return ToolResult(success=False, data="", error="cell reference required")
                sheet = params.get("sheet_name")
                result = await asyncio.to_thread(_update_cell, filepath, cell, value, sheet)
                return ToolResult(success=True, data=f"Updated {result['cell']} = {result['value']}")

            elif action == "add_formula":
                if not os.path.exists(filepath):
                    return ToolResult(success=False, data="", error=f"File not found: {safe_name}")
                cell = params.get("cell", "")
                formula = params.get("formula", "")
                if not cell or not formula:
                    return ToolResult(success=False, data="", error="cell and formula required")
                sheet = params.get("sheet_name")
                result = await asyncio.to_thread(_add_formula, filepath, cell, formula, sheet)
                return ToolResult(success=True, data=f"Formula set: {result['cell']} = {result['formula']}")

            else:
                return ToolResult(success=False, data="", error=f"Unknown action: {action}")

        except Exception as e:
            logger.warning("Spreadsheet operation failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))
