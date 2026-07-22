"""Create an Excel list of PowerPoint files found below configured folders.

The script reads a text file with one folder per line, searches each folder
recursively for PowerPoint files, and creates a macro-enabled Excel workbook.
The workbook contains clickable file-name hyperlinks, metadata, checkboxes, and
a "Copy" button that copies all checked files to Desktop\\PPT.

Usage:
    python scripts/search_ppt.py
    python scripts/search_ppt.py --output C:\\Temp\\ppt_liste.xlsm
    python scripts/search_ppt.py ordnerliste.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


POWERPOINT_EXTENSIONS = {
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".ppsm",
    ".pot",
    ".potx",
    ".potm",
}

XL_OPENXML_WORKBOOK_MACRO_ENABLED = 52
XL_CALCULATION_MANUAL = -4135

# Hier die zu durchsuchenden Ordner eintragen.
# Beispiel:
# SEARCH_FOLDERS = [
#     r"C:\Users\DeinName\Documents",
#     r"D:\Projekte",
# ]
SEARCH_FOLDERS = [
    #r"C:\Users\cbuehring\Desktop",
    #r"Z:\Mitarbeiter\cbuehring",
    r"\\meta-1.local\LW-Rechnung\LW-Rechnung",


    # r"C:\Pfad\zu\Ordner1",
    # r"D:\Pfad\zu\Ordner2",
]


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


@dataclass(frozen=True)
class PptFile:
    name: str
    path: Path
    modified: datetime
    size_bytes: int


def read_folder_list(folder_list_file: Path) -> list[Path]:
    """Read one folder path per line from a UTF-8 or Windows-encoded file."""
    if not folder_list_file.exists():
        raise FileNotFoundError(f"Ordnerlisten-Datei nicht gefunden: {folder_list_file}")

    raw = folder_list_file.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    base_dir = folder_list_file.parent
    folders: list[Path] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        value = line.strip().strip('"')
        if not value or value.startswith("#"):
            continue

        expanded = os.path.expandvars(os.path.expanduser(value))
        folder = Path(expanded)
        if not folder.is_absolute():
            folder = base_dir / folder

        folder = folder.resolve()
        if not folder.exists():
            log(f"Warnung: Zeile {line_number}: Ordner existiert nicht: {folder}")
            continue
        if not folder.is_dir():
            log(f"Warnung: Zeile {line_number}: Kein Ordner: {folder}")
            continue
        folders.append(folder)

    return folders


def read_configured_folders() -> list[Path]:
    """Read folders configured directly in SEARCH_FOLDERS."""
    folders: list[Path] = []
    for index, folder_text in enumerate(SEARCH_FOLDERS, start=1):
        value = str(folder_text).strip().strip('"')
        if not value:
            continue

        expanded = os.path.expandvars(os.path.expanduser(value))
        folder = Path(expanded).resolve()
        if not folder.exists():
            log(f"Warnung: SEARCH_FOLDERS Eintrag {index}: Ordner existiert nicht: {folder}")
            continue
        if not folder.is_dir():
            log(f"Warnung: SEARCH_FOLDERS Eintrag {index}: Kein Ordner: {folder}")
            continue
        folders.append(folder)

    return folders


def find_powerpoint_files(folders: list[Path]) -> list[PptFile]:
    """Search recursively for PowerPoint files below all folders."""
    found_by_path: dict[Path, PptFile] = {}

    for folder in folders:
        for root, dir_names, file_names in os.walk(folder, onerror=print_walk_error):
            log(f"Suche in: {root}")
            dir_names[:] = [name for name in dir_names if not name.startswith("$RECYCLE.BIN")]
            root_path = Path(root)
            for file_name in file_names:
                path = root_path / file_name
                if path.suffix.lower() not in POWERPOINT_EXTENSIONS:
                    continue
                try:
                    stat = path.stat()
                except OSError as exc:
                    log(f"Warnung: Datei uebersprungen ({path}): {exc}")
                    continue

                resolved = path.resolve()
                found_by_path[resolved] = PptFile(
                    name=path.name,
                    path=resolved,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    size_bytes=stat.st_size,
                )

    return sorted(found_by_path.values(), key=lambda item: (str(item.path.parent).lower(), item.name.lower()))


def print_walk_error(error: OSError) -> None:
    log(f"Warnung: Ordner uebersprungen: {error}")


def default_output_path() -> Path:
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    return desktop / "PowerPoint_Fundliste.xlsm"


def create_excel_report(ppt_files: list[PptFile], output_path: Path) -> None:
    """Create the macro-enabled workbook through Excel COM automation."""
    log("Starte Excel-Erstellung...")
    try:
        import win32com.client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Das Python-Paket 'pywin32' fehlt. Installiere es z.B. mit: python -m pip install pywin32"
        ) from exc

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.ScreenUpdating = False
    excel.EnableEvents = False
    previous_calculation = None
    try:
        previous_calculation = excel.Calculation
        excel.Calculation = XL_CALCULATION_MANUAL
    except Exception as exc:
        log(f"Hinweis: Excel-Berechnungsmodus bleibt unveraendert: {exc}")
    log("Excel gestartet.")

    workbook = None
    try:
        workbook = excel.Workbooks.Add()
        worksheet = workbook.Worksheets(1)
        worksheet.Name = "PowerPoint Dateien"

        log("Schreibe Tabelle...")
        write_table(worksheet, ppt_files)
        log("Fuege Makros ein...")
        add_copy_macro(workbook)

        log("Formatiere Arbeitsblatt...")
        worksheet.Columns("A:G").AutoFit()
        worksheet.Columns("B").ColumnWidth = min(max(worksheet.Columns("B").ColumnWidth, 60), 120)
        worksheet.Columns("E").ColumnWidth = 8
        worksheet.Columns("F:G").ColumnWidth = 14
        if ppt_files:
            worksheet.Range(f"A2:G{len(ppt_files) + 1}").RowHeight = 22
        worksheet.Rows(1).Font.Bold = True
        worksheet.Range("A1:G1").Interior.Color = 0xD9EAD3
        worksheet.Range("A1:G1").AutoFilter()

        log("Fuege Checkboxen und Buttons ein...")
        add_checkboxes(worksheet, len(ppt_files))
        add_row_action_buttons(worksheet, len(ppt_files))
        add_bottom_buttons(worksheet, len(ppt_files))

        worksheet.Application.ActiveWindow.SplitRow = 1
        worksheet.Application.ActiveWindow.FreezePanes = True

        log(f"Speichere Excel-Datei: {output_path}")
        workbook.SaveAs(str(output_path), FileFormat=XL_OPENXML_WORKBOOK_MACRO_ENABLED)
    except Exception:
        if workbook is not None:
            workbook.Close(SaveChanges=False)
        raise
    else:
        workbook.Close(SaveChanges=True)
    finally:
        try:
            if previous_calculation is not None:
                excel.Calculation = previous_calculation
            excel.EnableEvents = True
            excel.ScreenUpdating = True
        except Exception:
            pass
        excel.Quit()


def write_table(worksheet, ppt_files: list[PptFile]) -> None:
    headers = ["Dateiname", "Kompletter Pfad", "Datum der Datei", "Dateigroesse (MB)", "Copy", "Copy Datei", "OpenFolder"]
    for column, header in enumerate(headers, start=1):
        worksheet.Cells(1, column).Value = header

    for row, ppt_file in enumerate(ppt_files, start=2):
        worksheet.Cells(row, 1).Value = ppt_file.name
        worksheet.Hyperlinks.Add(
            Anchor=worksheet.Cells(row, 1),
            Address=str(ppt_file.path),
            TextToDisplay=ppt_file.name,
        )
        worksheet.Cells(row, 2).Value = str(ppt_file.path)
        worksheet.Cells(row, 3).Value = ppt_file.modified.strftime("%Y-%m-%d %H:%M:%S")
        worksheet.Cells(row, 4).Value = round(ppt_file.size_bytes / (1024 * 1024), 2)
        worksheet.Cells(row, 5).Value = False

    if ppt_files:
        worksheet.Range(f"C2:C{len(ppt_files) + 1}").NumberFormat = "yyyy-mm-dd hh:mm:ss"
        worksheet.Range(f"D2:D{len(ppt_files) + 1}").NumberFormat = "0.00"
        worksheet.Range(f"E2:E{len(ppt_files) + 1}").NumberFormat = ";;;"
        worksheet.Range(f"E2:E{len(ppt_files) + 1}").HorizontalAlignment = -4108


def add_checkboxes(worksheet, file_count: int) -> None:
    if file_count <= 0:
        return
    progress_step = progress_interval(file_count)
    for row in range(2, file_count + 2):
        cell = worksheet.Cells(row, 5)
        checkbox = worksheet.CheckBoxes().Add(cell.Left + 8, cell.Top + 2, 14, 14)
        checkbox.Caption = ""
        checkbox.LinkedCell = f"$E${row}"
        checkbox.Value = -4146  # xlOff
        report_progress("Checkboxen", row - 1, file_count, progress_step)


def add_row_action_buttons(worksheet, file_count: int) -> None:
    if file_count <= 0:
        return
    progress_step = progress_interval(file_count)
    for row in range(2, file_count + 2):
        copy_cell = worksheet.Cells(row, 6)
        copy_button = worksheet.Buttons().Add(copy_cell.Left + 2, copy_cell.Top + 2, 76, 18)
        copy_button.Caption = "Copy"
        copy_button.OnAction = "CopyRowPowerPoint"

        folder_cell = worksheet.Cells(row, 7)
        folder_button = worksheet.Buttons().Add(folder_cell.Left + 2, folder_cell.Top + 2, 88, 18)
        folder_button.Caption = "OpenFolder"
        folder_button.OnAction = "OpenRowFolder"
        report_progress("Zeilen-Buttons", row - 1, file_count, progress_step)


def progress_interval(total: int) -> int:
    if total <= 100:
        return 10
    if total <= 1000:
        return 50
    return 100


def report_progress(label: str, current: int, total: int, step: int) -> None:
    if current == 1 or current == total or current % step == 0:
        log(f"{label}: {current}/{total}")


def add_bottom_buttons(worksheet, file_count: int) -> None:
    button_row = file_count + 4
    cell = worksheet.Cells(button_row, 1)
    button = worksheet.Buttons().Add(cell.Left, cell.Top, 90, 28)
    button.Caption = "Copy"
    button.OnAction = "CopySelectedPowerPoints"
    worksheet.Cells(button_row, 2).Value = "Kopiert alle markierten Dateien nach Desktop\\PPT"

    check_cell = worksheet.Cells(button_row, 4)
    check_button = worksheet.Buttons().Add(check_cell.Left, check_cell.Top, 90, 28)
    check_button.Caption = "Check All"
    check_button.OnAction = "CheckAllPowerPoints"

    uncheck_cell = worksheet.Cells(button_row, 5)
    uncheck_button = worksheet.Buttons().Add(uncheck_cell.Left, uncheck_cell.Top, 90, 28)
    uncheck_button.Caption = "Uncheck"
    uncheck_button.OnAction = "UncheckAllPowerPoints"


def add_copy_macro(workbook) -> None:
    macro_code = r'''
Option Explicit

Sub CopySelectedPowerPoints()
    Dim ws As Worksheet
    Dim lastRow As Long
    Dim rowIndex As Long
    Dim sourcePath As String
    Dim desktopPath As String
    Dim targetFolder As String
    Dim targetPath As String
    Dim copiedCount As Long
    Dim fso As Object

    Set ws = ThisWorkbook.Worksheets("PowerPoint Dateien")
    Set fso = CreateObject("Scripting.FileSystemObject")

    desktopPath = CreateObject("WScript.Shell").SpecialFolders("Desktop")
    targetFolder = fso.BuildPath(desktopPath, "PPT")
    If Not fso.FolderExists(targetFolder) Then
        fso.CreateFolder targetFolder
    End If

    lastRow = ws.Cells(ws.Rows.Count, 2).End(xlUp).Row
    For rowIndex = 2 To lastRow
        If CBool(ws.Cells(rowIndex, 5).Value) Then
            sourcePath = CStr(ws.Cells(rowIndex, 2).Value)
            If Len(sourcePath) > 0 And fso.FileExists(sourcePath) Then
                targetPath = UniqueTargetPath(fso, targetFolder, fso.GetFileName(sourcePath))
                fso.CopyFile sourcePath, targetPath, False
                copiedCount = copiedCount + 1
            End If
        End If
    Next rowIndex

    MsgBox copiedCount & " Datei(en) nach " & targetFolder & " kopiert.", vbInformation, "Copy"
End Sub

Sub CopyRowPowerPoint()
    Dim ws As Worksheet
    Dim rowIndex As Long
    Dim sourcePath As String
    Dim targetFolder As String
    Dim targetPath As String
    Dim fso As Object

    Set ws = ThisWorkbook.Worksheets("PowerPoint Dateien")
    rowIndex = ws.Buttons(Application.Caller).TopLeftCell.Row
    sourcePath = CStr(ws.Cells(rowIndex, 2).Value)

    If Len(sourcePath) = 0 Then Exit Sub

    Set fso = CreateObject("Scripting.FileSystemObject")
    If Not fso.FileExists(sourcePath) Then
        MsgBox "Datei nicht gefunden:" & vbCrLf & sourcePath, vbExclamation, "Copy"
        Exit Sub
    End If

    targetFolder = fso.BuildPath(CreateObject("WScript.Shell").SpecialFolders("Desktop"), "PPT")
    If Not fso.FolderExists(targetFolder) Then
        fso.CreateFolder targetFolder
    End If

    targetPath = UniqueTargetPath(fso, targetFolder, fso.GetFileName(sourcePath))
    fso.CopyFile sourcePath, targetPath, False
    MsgBox "Datei kopiert nach:" & vbCrLf & targetPath, vbInformation, "Copy"
End Sub

Sub OpenRowFolder()
    Dim ws As Worksheet
    Dim rowIndex As Long
    Dim sourcePath As String
    Dim fso As Object

    Set ws = ThisWorkbook.Worksheets("PowerPoint Dateien")
    rowIndex = ws.Buttons(Application.Caller).TopLeftCell.Row
    sourcePath = CStr(ws.Cells(rowIndex, 2).Value)

    Set fso = CreateObject("Scripting.FileSystemObject")
    If Len(sourcePath) = 0 Or Not fso.FileExists(sourcePath) Then
        MsgBox "Datei nicht gefunden:" & vbCrLf & sourcePath, vbExclamation, "OpenFolder"
        Exit Sub
    End If

    Shell "explorer.exe /select,""" & sourcePath & """", vbNormalFocus
End Sub

Sub CheckAllPowerPoints()
    SetCopySelection True
End Sub

Sub UncheckAllPowerPoints()
    SetCopySelection False
End Sub

Private Sub SetCopySelection(ByVal selected As Boolean)
    Dim ws As Worksheet
    Dim lastRow As Long
    Dim rowIndex As Long

    Set ws = ThisWorkbook.Worksheets("PowerPoint Dateien")
    lastRow = ws.Cells(ws.Rows.Count, 2).End(xlUp).Row

    For rowIndex = 2 To lastRow
        If Len(CStr(ws.Cells(rowIndex, 2).Value)) > 0 Then
            ws.Cells(rowIndex, 5).Value = selected
        End If
    Next rowIndex
End Sub

Private Function UniqueTargetPath(ByVal fso As Object, ByVal targetFolder As String, ByVal fileName As String) As String
    Dim baseName As String
    Dim extensionName As String
    Dim candidate As String
    Dim index As Long

    baseName = fso.GetBaseName(fileName)
    extensionName = fso.GetExtensionName(fileName)
    candidate = fso.BuildPath(targetFolder, fileName)
    index = 1

    Do While fso.FileExists(candidate)
        If Len(extensionName) > 0 Then
            candidate = fso.BuildPath(targetFolder, baseName & " (" & index & ")." & extensionName)
        Else
            candidate = fso.BuildPath(targetFolder, baseName & " (" & index & ")")
        End If
        index = index + 1
    Loop

    UniqueTargetPath = candidate
End Function
'''
    try:
        module = workbook.VBProject.VBComponents.Add(1)
        module.CodeModule.AddFromString(macro_code)
    except Exception as exc:
        raise RuntimeError(
            "Excel konnte das VBA-Makro nicht einfuegen. Aktiviere in Excel unter "
            "'Datei > Optionen > Trust Center > Einstellungen fuer das Trust Center > "
            "Makroeinstellungen' die Option 'Zugriff auf das VBA-Projektobjektmodell vertrauen'."
        ) from exc


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Durchsucht Ordner aus einer Textdatei nach PowerPoint-Dateien und erstellt eine Excel-Liste."
    )
    parser.add_argument(
        "folder_list",
        nargs="?",
        type=Path,
        help="Optional: Textdatei mit einem zu durchsuchenden Ordner pro Zeile. Ohne Angabe wird SEARCH_FOLDERS im Script genutzt.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=default_output_path(),
        help="Ausgabedatei (.xlsm). Standard: Desktop\\PowerPoint_Fundliste_lwrechnung.xlsm",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    folders = read_folder_list(args.folder_list) if args.folder_list else read_configured_folders()
    if not folders:
        log("Keine gueltigen Ordner gefunden. Trage Ordner oben im Script in SEARCH_FOLDERS ein.")
        return 2

    log(f"Starte Suche in {len(folders)} Ordner(n).")
    ppt_files = find_powerpoint_files(folders)
    log(f"Suche beendet: {len(ppt_files)} PowerPoint-Datei(en) gefunden.")
    create_excel_report(ppt_files, args.output)

    log(f"Excel-Datei erstellt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
