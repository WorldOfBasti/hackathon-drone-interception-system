import SwiftUI
import UIKit

struct RecordingExportsView: View {
    let isRecording: Bool

    @Environment(\.dismiss) private var dismiss
    @State private var recordings: [RecordingExportItem] = []
    @State private var errorText: String?
    @State private var sharePackage: RecordingSharePackage?

    var body: some View {
        NavigationStack {
            Group {
                if let errorText {
                    ContentUnavailableView(
                        "Recordings unavailable",
                        systemImage: "exclamationmark.triangle",
                        description: Text(errorText)
                    )
                } else if recordings.isEmpty {
                    ContentUnavailableView(
                        "No recordings yet",
                        systemImage: "video.slash",
                        description: Text("Stop a recording first, then export the MOV and metadata JSON from here.")
                    )
                } else {
                    List(recordings) { recording in
                        RecordingExportRow(recording: recording) {
                            sharePackage = RecordingSharePackage(urls: recording.exportURLs)
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Recordings")
            .navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .top) {
                if isRecording {
                    Text("Recording is active. Stop before exporting the current session.")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(.orange)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal)
                        .padding(.vertical, 8)
                        .background(Color.orange.opacity(0.12))
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") {
                        dismiss()
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        loadRecordings()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh Recordings")
                }
            }
        }
        .onAppear(perform: loadRecordings)
        .sheet(item: $sharePackage) { package in
            ActivityView(activityItems: package.urls)
        }
    }

    private func loadRecordings() {
        do {
            recordings = try RecordingExportItem.loadAll()
            errorText = nil
        } catch {
            recordings = []
            errorText = error.localizedDescription
        }
    }
}

private struct RecordingExportRow: View {
    let recording: RecordingExportItem
    let onExport: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(recording.title)
                    .font(.system(.subheadline, design: .monospaced, weight: .semibold))
                    .lineLimit(1)
                    .truncationMode(.middle)

                Text(recording.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer(minLength: 8)

            Button(action: onExport) {
                Image(systemName: "square.and.arrow.up")
                    .font(.system(size: 17, weight: .semibold))
                    .frame(width: 36, height: 36)
            }
            .buttonStyle(.bordered)
            .accessibilityLabel("Export \(recording.title)")
        }
        .padding(.vertical, 5)
    }
}

private struct RecordingExportItem: Identifiable {
    let id: String
    let videoURL: URL
    let metadataURL: URL?
    let createdAt: Date?
    let byteCount: Int64

    var title: String {
        videoURL.deletingPathExtension().lastPathComponent
    }

    var exportURLs: [URL] {
        [videoURL, metadataURL].compactMap { $0 }
    }

    var subtitle: String {
        let parts = [
            formattedDate,
            ByteCountFormatter.string(fromByteCount: byteCount, countStyle: .file),
            metadataURL == nil ? "metadata missing" : "MOV + JSON"
        ].compactMap { $0 }

        return parts.joined(separator: "  |  ")
    }

    private var formattedDate: String? {
        guard let createdAt else { return nil }
        return Self.dateFormatter.string(from: createdAt)
    }

    static func loadAll() throws -> [RecordingExportItem] {
        let directory = try Recorder.recordingsDirectory()
        let urls = try FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.creationDateKey, .contentModificationDateKey, .fileSizeKey],
            options: [.skipsHiddenFiles]
        )

        let jsonURLs = Dictionary(
            uniqueKeysWithValues: urls
                .filter { $0.pathExtension.lowercased() == "json" }
                .map { ($0.lastPathComponent, $0) }
        )

        return try urls
            .filter { $0.pathExtension.lowercased() == "mov" }
            .map { videoURL in
                let metadataName = "\(videoURL.deletingPathExtension().lastPathComponent)_metadata.json"
                let metadataURL = jsonURLs[metadataName]
                let videoValues = try videoURL.resourceValues(forKeys: [.creationDateKey, .contentModificationDateKey, .fileSizeKey])
                let metadataSize = try metadataURL?.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0

                return RecordingExportItem(
                    id: videoURL.path,
                    videoURL: videoURL,
                    metadataURL: metadataURL,
                    createdAt: videoValues.creationDate ?? videoValues.contentModificationDate,
                    byteCount: Int64(videoValues.fileSize ?? 0) + Int64(metadataSize)
                )
            }
            .sorted {
                ($0.createdAt ?? .distantPast) > ($1.createdAt ?? .distantPast)
            }
    }

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        formatter.timeStyle = .medium
        return formatter
    }()
}

private struct RecordingSharePackage: Identifiable {
    let id = UUID()
    let urls: [URL]
}

private struct ActivityView: UIViewControllerRepresentable {
    let activityItems: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
