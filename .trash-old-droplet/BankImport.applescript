-- Halifax CSV Import droplet
-- Drop a Halifax CSV onto this app's icon, or double-click to pick one.
-- Runs append_csv.py which appends rows, sorts by date, and rebuilds the dashboard.

property bankDir : "/Users/ronaldniddrie/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions"
property wrapperScript : bankDir & "/automation/scripts/run_append.sh"
property workbook : bankDir & "/Banking Transactions Live.xlsm"

on open theFiles
	processFiles(theFiles)
end open

on run
	set theFile to choose file with prompt "Select a Halifax CSV to import:" of type {"csv", "public.comma-separated-values-text"}
	processFiles({theFile})
end run

on processFiles(theFiles)
	set okCount to 0
	set failCount to 0
	repeat with f in theFiles
		set fPath to POSIX path of (f as alias)
		try
			do shell script quoted form of wrapperScript & " --csv " & quoted form of fPath
			set okCount to okCount + 1
		on error errMsg
			set failCount to failCount + 1
			display dialog "Import failed for:" & return & fPath & return & return & errMsg with title "Bank Import Error" buttons {"OK"} default button "OK" with icon stop
		end try
	end repeat
	if okCount > 0 then
		display notification (okCount as string) & " file(s) imported. Opening workbook…" with title "Bank Import" subtitle "Complete"
		tell application "Microsoft Excel"
			activate
			open POSIX file workbook
		end tell
	end if
end processFiles
