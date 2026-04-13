Attribute VB_Name = "SortByDateDesc"
' ===============================================================
' SortByDateDesc
'   Sorts the "2017 To Present" sheet by Transaction Date,
'   newest first. Handles Table4's shared formulas natively
'   because Excel does the sort itself.
'
'   Trigger options:
'     - Alt+F8 -> SortByDateDesc -> Run
'     - Assign to a shape/button on the sheet
'     - Bind to Ctrl+Shift+S via Macro Options (optional)
'
'   Safe to run any time — it's idempotent.
' ===============================================================
Option Explicit

Public Sub SortByDateDesc()
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim sortCol As Range

    On Error GoTo ErrHandler

    Set ws = ThisWorkbook.Sheets("2017 To Present")
    If ws Is Nothing Then
        MsgBox "Sheet '2017 To Present' not found.", vbCritical
        Exit Sub
    End If

    Set tbl = ws.ListObjects("Table4")
    If tbl Is Nothing Then
        MsgBox "Table 'Table4' not found on sheet '2017 To Present'.", vbCritical
        Exit Sub
    End If

    Set sortCol = tbl.ListColumns("Transaction Date").DataBodyRange

    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual

    With tbl.Sort
        .SortFields.Clear
        .SortFields.Add Key:=sortCol, _
                        SortOn:=xlSortOnValues, _
                        Order:=xlDescending, _
                        DataOption:=xlSortNormal
        .Header = xlYes
        .MatchCase = False
        .Orientation = xlTopToBottom
        .Apply
    End With

    Application.Calculation = xlCalculationAutomatic
    Application.ScreenUpdating = True
    Application.Calculate

    ' Optional quiet confirmation — comment out if you want silent runs
    ' MsgBox "Sorted by Transaction Date (newest first).", vbInformation
    Exit Sub

ErrHandler:
    Application.Calculation = xlCalculationAutomatic
    Application.ScreenUpdating = True
    MsgBox "SortByDateDesc failed: " & Err.Description, vbExclamation
End Sub

' ---------------------------------------------------------------
' SortAndSave — same as above, then saves the workbook.
' Useful when running from an external trigger (AppleScript,
' scheduled task) where you want the file persisted on disk.
' ---------------------------------------------------------------
Public Sub SortAndSave()
    Call SortByDateDesc
    ThisWorkbook.Save
End Sub
