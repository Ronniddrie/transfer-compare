import Cocoa
import WebKit

// MARK: - App Delegate
class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: DropWebView!
    var dropOverlay: DropOverlayView!

    let bankDir = NSString(string: "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions").expandingTildeInPath
    let localInbox = NSString(string: "~/Library/Application Support/BankImport/Inbox").expandingTildeInPath

    func applicationDidFinishLaunching(_ notification: Notification) {
        let screenRect = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        let windowWidth: CGFloat = min(1100, screenRect.width * 0.7)
        let windowHeight: CGFloat = min(800, screenRect.height * 0.85)
        let windowX = screenRect.origin.x + (screenRect.width - windowWidth) / 2
        let windowY = screenRect.origin.y + (screenRect.height - windowHeight) / 2

        window = NSWindow(
            contentRect: NSRect(x: windowX, y: windowY, width: windowWidth, height: windowHeight),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "BankImport"
        window.minSize = NSSize(width: 600, height: 400)
        window.isReleasedWhenClosed = false

        let contentView = NSView(frame: window.contentView!.bounds)
        contentView.autoresizingMask = [.width, .height]
        window.contentView = contentView

        // Create custom WKWebView that handles drag-and-drop
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        webView = DropWebView(frame: contentView.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.appDelegate = self
        contentView.addSubview(webView)

        // Create drop overlay (shown during drag hover)
        dropOverlay = DropOverlayView(frame: contentView.bounds)
        dropOverlay.autoresizingMask = [.width, .height]
        dropOverlay.isHidden = true
        contentView.addSubview(dropOverlay)

        // Inject JavaScript to block web-level drag handling after page loads
        webView.navigationDelegate = self

        loadDashboard()

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func loadDashboard() {
        let dashboardPath = (bankDir as NSString).appendingPathComponent("bank_dashboard.html")
        let dashboardURL = URL(fileURLWithPath: dashboardPath)

        if FileManager.default.fileExists(atPath: dashboardPath) {
            webView.loadFileURL(dashboardURL, allowingReadAccessTo: URL(fileURLWithPath: bankDir))
        } else {
            let html = """
            <!doctype html>
            <html><head><meta charset="utf-8"><title>BankImport</title>
            <style>body{font-family:-apple-system,sans-serif;background:#0f1420;color:#c6e0f2;padding:40px;text-align:center}</style>
            </head><body>
            <h1>Dashboard not found</h1>
            <p>Expected: \(dashboardPath)</p>
            </body></html>
            """
            webView.loadHTMLString(html, baseURL: nil)
        }
    }

    func handleDroppedFiles(_ urls: [URL]) {
        let fm = FileManager.default
        try? fm.createDirectory(atPath: localInbox, withIntermediateDirectories: true)

        let logPath = (bankDir as NSString).appendingPathComponent("automation/bankimport_platypus.log")
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        var logLines = ["-----", formatter.string(from: Date()), "drop: \(urls.map { $0.lastPathComponent })"]

        var csvCount = 0
        for url in urls {
            if url.pathExtension.lowercased() == "csv" {
                let dest = URL(fileURLWithPath: localInbox).appendingPathComponent(url.lastPathComponent)
                do {
                    if fm.fileExists(atPath: dest.path) { try fm.removeItem(at: dest) }
                    try fm.copyItem(at: url, to: dest)
                    logLines.append("  copied to inbox: \(url.lastPathComponent)")
                    csvCount += 1
                } catch {
                    logLines.append("  FAILED: \(url.lastPathComponent): \(error.localizedDescription)")
                }
            } else {
                logLines.append("  skipping non-CSV: \(url.lastPathComponent)")
            }
        }

        if csvCount > 0 {
            logLines.append("  \(csvCount) CSV(s) queued — launchd watcher will process shortly")
            DispatchQueue.main.async { self.showSuccess(count: csvCount) }
        }

        let logEntry = logLines.joined(separator: "\n") + "\n"
        if let data = logEntry.data(using: .utf8) {
            if fm.fileExists(atPath: logPath),
               let handle = FileHandle(forWritingAtPath: logPath) {
                handle.seekToEndOfFile()
                handle.write(data)
                handle.closeFile()
            } else {
                fm.createFile(atPath: logPath, contents: data)
            }
        }
    }

    func showSuccess(count: Int) {
        dropOverlay.showSuccess(message: "\(count) CSV\(count == 1 ? "" : "s") queued for import!")
        DispatchQueue.main.asyncAfter(deadline: .now() + 8.0) { [weak self] in
            self?.loadDashboard()
        }
    }

    // Handle files opened via Dock icon drop or "Open With"
    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        let urls = filenames.map { URL(fileURLWithPath: $0) }
        let csvFiles = urls.filter { $0.pathExtension.lowercased() == "csv" }
        if !csvFiles.isEmpty { handleDroppedFiles(csvFiles) }
        sender.reply(toOpenOrPrint: .success)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

// MARK: - Navigation delegate to inject drag-blocking JS after page loads
extension AppDelegate: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Block the HTML page from handling drag events so native overrides work
        let js = "document.addEventListener('dragover',function(e){e.preventDefault();e.stopPropagation()},true);document.addEventListener('drop',function(e){e.preventDefault();e.stopPropagation()},true);document.addEventListener('dragenter',function(e){e.preventDefault();e.stopPropagation()},true);"
        webView.evaluateJavaScript(js, completionHandler: nil)
    }
}

// MARK: - WKWebView subclass that intercepts drag-and-drop
class DropWebView: WKWebView {
    weak var appDelegate: AppDelegate?

    override init(frame: CGRect, configuration: WKWebViewConfiguration) {
        super.init(frame: frame, configuration: configuration)
        registerForDraggedTypes([.fileURL])
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        registerForDraggedTypes([.fileURL])
    }

    // --- Drag destination methods (override WKWebView's defaults) ---

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        if hasCSVFiles(sender) {
            appDelegate?.dropOverlay.isHidden = false
            appDelegate?.dropOverlay.setHighlighted(true)
            return .copy
        }
        return []
    }

    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        return hasCSVFiles(sender) ? .copy : []
    }

    override func draggingExited(_ sender: NSDraggingInfo?) {
        appDelegate?.dropOverlay.isHidden = true
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        appDelegate?.dropOverlay.isHidden = true

        guard let items = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [
            .urlReadingFileURLsOnly: true
        ]) as? [URL] else { return false }

        let csvFiles = items.filter { $0.pathExtension.lowercased() == "csv" }
        guard !csvFiles.isEmpty else { return false }

        appDelegate?.handleDroppedFiles(csvFiles)
        return true
    }

    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        return hasCSVFiles(sender)
    }

    private func hasCSVFiles(_ sender: NSDraggingInfo) -> Bool {
        guard let items = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [
            .urlReadingFileURLsOnly: true
        ]) as? [URL] else { return false }
        return items.contains { $0.pathExtension.lowercased() == "csv" }
    }
}

// MARK: - Visual overlay for drag feedback
class DropOverlayView: NSView {
    private var label: NSTextField!

    override init(frame: NSRect) {
        super.init(frame: frame)
        setupUI()
    }
    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setupUI()
    }

    private func setupUI() {
        wantsLayer = true
        layer?.backgroundColor = NSColor(calibratedRed: 0.1, green: 0.4, blue: 0.9, alpha: 0.35).cgColor
        layer?.borderColor = NSColor(calibratedRed: 0.3, green: 0.6, blue: 1.0, alpha: 0.9).cgColor
        layer?.borderWidth = 3
        layer?.cornerRadius = 12

        label = NSTextField(labelWithString: "Drop CSV files here")
        label.font = NSFont.systemFont(ofSize: 24, weight: .bold)
        label.textColor = .white
        label.alignment = .center
        label.backgroundColor = .clear
        label.translatesAutoresizingMaskIntoConstraints = false
        addSubview(label)

        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: centerXAnchor),
            label.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    func setHighlighted(_ on: Bool) {
        layer?.backgroundColor = on
            ? NSColor(calibratedRed: 0.1, green: 0.4, blue: 0.9, alpha: 0.4).cgColor
            : NSColor(calibratedRed: 0.3, green: 0.3, blue: 0.3, alpha: 0.3).cgColor
        label.stringValue = on ? "Drop CSV files here" : "Only CSV files accepted"
    }

    func showSuccess(message: String) {
        isHidden = false
        layer?.backgroundColor = NSColor(calibratedRed: 0.1, green: 0.7, blue: 0.3, alpha: 0.5).cgColor
        layer?.borderColor = NSColor(calibratedRed: 0.2, green: 0.9, blue: 0.4, alpha: 0.9).cgColor
        label.stringValue = message

        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
            self?.isHidden = true
            self?.layer?.borderColor = NSColor(calibratedRed: 0.3, green: 0.6, blue: 1.0, alpha: 0.9).cgColor
        }
    }

    // Let all mouse events pass through to the web view below
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

// MARK: - Main
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
