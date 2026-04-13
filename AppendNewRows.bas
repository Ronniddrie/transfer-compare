Attribute VB_Name = "modAppendNewRows"
Option Explicit

' ======================================================================
' AppendNewRows  (v2 — Table4 / ListObject aware)
'
' Reads new_rows_to_append.tsv from the same folder as this workbook and
' appends every new row INSIDE the "Table4" Excel Table on the
' "2017 To Present" sheet. Because the 4 slicers (Category, Month, Year,
' Transaction Type) are bound to Table4, they will auto-include the new
' rows as soon as this macro finishes — no manual slicer refresh needed.
'
' The macro:
'   * Temporarily hides the Totals row so it can grow the table cleanly.
'   * Resizes the ListObject via lo.Resize, which preserves the table
'     style, calculated columns (Month / Year), and slicer bindings.
'   * Writes only columns A, D-I. Columns B (Month) and C (Year) are
'     LEFT ALONE so Excel's calculated-column formulas fill them.
'   * Skips any TSV row whose date is on or before the table's current
'     maximum date, so re-running is safe (no duplicates).
'   * Restores the Totals row at the end.
'
' TSV format (tab-delimited, 9 columns):
'   A Transaction Date (yyyy-mm-dd)
'   B Month (text, ignored — calc column)
'   C Year (number, ignored — calc column)
'   D Transaction Type
'   E Transaction Description
'   F Category
'   G Debit Amount
'   H Credit Amount
'   I Balance
' ======================================================================

Sub AppendNewRows()
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Sheets("2017 To Present")
    On Error GoTo 0
    If ws Is Nothing Then
        MsgBox "Sheet '2017 To Present' not found.", vbCritical
        Exit Sub
    End If

    Dim lo As ListObject
    On Error Resume Next
    Set lo = ws.ListObjects("Table4")
    On Error GoTo 0
    If lo Is Nothing Then
        If ws.ListObjects.Count > 0 Then Set lo = ws.ListObjects(1)
    End If
    If lo Is Nothing Then
        MsgBox "Couldn't find an Excel Table on the sheet. " & _
               "The slicers are bound to a Table, so the new rows must go inside it.", _
               vbCritical
        Exit Sub
    End If

    Dim tsvPath As String
    tsvPath = ThisWorkbook.Path & Application.PathSeparator & "new_rows_to_append.tsv"
    If Dir(tsvPath) = "" Then
        MsgBox "Can't find:" & vbCrLf & tsvPath, vbExclamation
        Exit Sub
    End If

    ' --- Find the latest date already inside the table ---
    Dim lastDate As Date
    lastDate = 0
    If lo.ListRows.Count > 0 Then
        Dim dateVals As Variant
        dateVals = lo.ListColumns(1).DataBodyRange.Value
        Dim k As Long
        If IsArray(dateVals) Then
            For k = 1 To UBound(dateVals, 1)
                If IsDate(dateVals(k, 1)) Then
                    If CDate(dateVals(k, 1)) > lastDate Then lastDate = CDate(dateVals(k, 1))
                End If
            Next k
        Else
            If IsDate(dateVals) Then lastDate = CDate(dateVals)
        End If
    End If

    ' --- Read TSV and filter rows strictly after lastDate ---
    Dim fNum As Integer
    fNum = FreeFile
    Open tsvPath For Input As #fNum

    Dim buf() As String
    ReDim buf(1 To 20000)
    Dim nBuf As Long, skipped As Long
    Dim lineText As String, d As Date

    Do While Not EOF(fNum)
        Line Input #fNum, lineText
        If Len(lineText) > 0 Then
            If Len(lineText) >= 10 Then
                d = DateSerial(CInt(Mid$(lineText, 1, 4)), _
                               CInt(Mid$(lineText, 6, 2)), _
                               CInt(Mid$(lineText, 9, 2)))
            Else
                d = 0
            End If
            If d > lastDate Then
                nBuf = nBuf + 1
                If nBuf > UBound(buf) Then ReDim Preserve buf(1 To UBound(buf) + 10000)
                buf(nBuf) = lineText
            Else
                skipped = skipped + 1
            End If
        End If
    Loop
    Close #fNum

    If nBuf = 0 Then
        MsgBox "Nothing to add." & vbCrLf & _
               "The TSV contained " & skipped & " rows, all dated " & _
               Format(lastDate, "yyyy-mm-dd") & " or earlier.", _
               vbInformation, "AppendNewRows"
        Exit Sub
    End If

    ' --- Build the write arrays: column A (date) and columns D-I ---
    Dim dateArr() As Variant
    Dim dataArr() As Variant
    ReDim dateArr(1 To nBuf, 1 To 1)
    ReDim dataArr(1 To nBuf, 1 To 6)

    Dim i As Long, parts() As String
    For i = 1 To nBuf
        parts = Split(buf(i), vbTab)
        dateArr(i, 1) = DateSerial(CInt(Mid$(parts(0), 1, 4)), _
                                   CInt(Mid$(parts(0), 6, 2)), _
                                   CInt(Mid$(parts(0), 9, 2)))
        dataArr(i, 1) = SafePart(parts, 3)              ' D Transaction Type
        dataArr(i, 2) = SafePart(parts, 4)              ' E Description
        dataArr(i, 3) = SafePart(parts, 5)              ' F Category
        dataArr(i, 4) = ToNumOrEmpty(SafePart(parts, 6)) ' G Debit
        dataArr(i, 5) = ToNumOrEmpty(SafePart(parts, 7)) ' H Credit
        dataArr(i, 6) = ToNumOrEmpty(SafePart(parts, 8)) ' I Balance
    Next i

    ' --- Resize table and write data ---
    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual
    Application.EnableEvents = False

    Dim hadTotals As Boolean
    hadTotals = lo.ShowTotals
    If hadTotals Then lo.ShowTotals = False

    Dim hdrRow As Long, firstCol As Long, colCount As Long
    hdrRow = lo.HeaderRowRange.Row
    firstCol = lo.HeaderRowRange.Column
    colCount = lo.ListColumns.Count

    Dim curLastRow As Long
    curLastRow = hdrRow + lo.ListRows.Count          ' current last data row

    Dim newLastRow As Long
    newLastRow = curLastRow + nBuf

    ' Expand the table to cover the new rows
    lo.Resize ws.Range(ws.Cells(hdrRow, firstCol), _
                       ws.Cells(newLastRow, firstCol + colCount - 1))

    ' Write column A (Date) — calc columns B/C will auto-fill from this
    ws.Range(ws.Cells(curLastRow + 1, firstCol), _
             ws.Cells(newLastRow, firstCol)).Value = dateArr

    ' Write columns D-I (skipping calc columns B and C)
    ws.Range(ws.Cells(curLastRow + 1, firstCol + 3), _
             ws.Cells(newLastRow, firstCol + 8)).Value = dataArr

    ' Restore Totals row
    If hadTotals Then lo.ShowTotals = True

    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
    Application.CalculateFull
    Application.ScreenUpdating = True

    MsgBox "Added " & nBuf & " rows to table " & lo.Name & "." & vbCrLf & _
           "Skipped " & skipped & " rows dated on/before " & _
               Format(lastDate, "yyyy-mm-dd") & "." & vbCrLf & _
           "Table now has " & lo.ListRows.Count & " data rows." & vbCrLf & vbCrLf & _
           "If the slicers don't refresh on their own, right-click any slicer " & _
           "and choose 'Refresh'.", _
           vbInformation, "AppendNewRows complete"
End Sub

Private Function SafePart(ByRef parts() As String, ByVal idx As Long) As String
    If idx >= 0 And idx <= UBound(parts) Then
        SafePart = parts(idx)
    Else
        SafePart = ""
    End If
End Function

Private Function ToNumOrEmpty(ByVal s As String) As Variant
    If Len(s) = 0 Then
        ToNumOrEmpty = ""   ' keep the cell blank, not zero
    ElseIf IsNumeric(s) Then
        ToNumOrEmpty = CDbl(s)
    Else
        ToNumOrEmpty = s
    End If
End Function
