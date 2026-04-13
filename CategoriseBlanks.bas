Attribute VB_Name = "modCategoriseBlanks"
Option Explicit

' ----------------------------------------------------------------------
' CategoriseBlanks
'   Scans the "2017 To Present" sheet, learns Description -> Category
'   rules from rows that are already categorised, then fills any blank
'   Category cells (column F) where the Description (column E) matches
'   a known rule. Leaves unknown descriptions blank.
'
'   Safe to re-run any time — it only touches blank Category cells.
'   Mac & Windows compatible (uses a Collection, not Scripting.Dictionary).
' ----------------------------------------------------------------------
Sub CategoriseBlanks()
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Sheets("2017 To Present")
    On Error GoTo 0
    If ws Is Nothing Then
        MsgBox "Could not find sheet '2017 To Present'.", vbExclamation
        Exit Sub
    End If

    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual
    Application.EnableEvents = False

    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, "E").End(xlUp).Row
    If lastRow < 2 Then GoTo Cleanup

    ' Read columns E and F in one shot
    Dim data As Variant
    data = ws.Range("E2:F" & lastRow).Value

    ' Pass 1: build Description -> Category map (first seen wins)
    Dim map As Collection
    Set map = New Collection
    Dim i As Long, desc As String, cat As String
    For i = 1 To UBound(data, 1)
        desc = Trim$(CStr(data(i, 1)))
        cat = Trim$(CStr(data(i, 2)))
        If Len(desc) > 0 And Len(cat) > 0 Then
            On Error Resume Next
            map.Add cat, desc   ' key = description; duplicates ignored
            On Error GoTo 0
        End If
    Next i

    ' Pass 2: fill blanks where we have a rule
    Dim filled As Long, found As String
    For i = 1 To UBound(data, 1)
        desc = Trim$(CStr(data(i, 1)))
        cat = Trim$(CStr(data(i, 2)))
        If Len(desc) > 0 And Len(cat) = 0 Then
            found = ""
            On Error Resume Next
            found = map(desc)
            On Error GoTo 0
            If Len(found) > 0 Then
                data(i, 2) = found
                filled = filled + 1
            End If
        End If
    Next i

    ' Write back ONLY column F (leaves column E completely untouched)
    Dim outF() As Variant
    ReDim outF(1 To UBound(data, 1), 1 To 1)
    For i = 1 To UBound(data, 1)
        outF(i, 1) = data(i, 2)
    Next i
    ws.Range("F2:F" & lastRow).Value = outF

    MsgBox "Done. Filled " & filled & " Category cells." & vbCrLf & _
           "Rules learned: " & map.Count, vbInformation, "Categorise Blanks"

Cleanup:
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
    Application.ScreenUpdating = True
End Sub
