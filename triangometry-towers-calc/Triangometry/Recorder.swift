import ARKit
import AVFoundation
import Foundation

final class Recorder {
    private enum State {
        case idle
        case recording
        case failed
    }

    private let queue = DispatchQueue(label: "triangometry.recorder.queue")
    private var state: State = .idle
    private var assetWriter: AVAssetWriter?
    private var videoInput: AVAssetWriterInput?
    private var pixelBufferAdaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var metadataWriter: MetadataWriter?
    private var outputURL: URL?
    private var metadataURL: URL?
    private var sessionID = ""
    private var deviceID = ""
    private var firstARTimestamp: TimeInterval?
    private var lastPresentationTime = CMTime.negativeInfinity
    private var frameCount = 0
    private var droppedFrameCount = 0
    private var startedAt = Date()

    func start(deviceID rawDeviceID: String) throws -> RecordingStartInfo {
        try queue.sync {
            guard state == .idle else { throw RecorderError.alreadyRecording }

            startedAt = Date()
            sessionID = Self.filenameDateFormatter.string(from: startedAt)
            deviceID = rawDeviceID.filenameSafe(defaultValue: "iphone1")

            let directory = try Self.recordingsDirectory()
            let baseName = "recording_\(sessionID)_\(deviceID)"
            let videoURL = directory.appendingPathComponent("\(baseName).mov")
            let metadataURL = directory.appendingPathComponent("\(baseName)_metadata.json")

            try FileManager.default.removeItemIfExists(at: videoURL)
            try FileManager.default.removeItemIfExists(at: metadataURL)

            outputURL = videoURL
            self.metadataURL = metadataURL
            frameCount = 0
            droppedFrameCount = 0
            firstARTimestamp = nil
            lastPresentationTime = .negativeInfinity

            let sessionInfo = RecordingSessionInfo(
                sessionID: sessionID,
                deviceID: deviceID,
                createdAtISO8601: ISO8601DateFormatter().string(from: startedAt),
                videoFilename: videoURL.lastPathComponent,
                metadataFilename: metadataURL.lastPathComponent,
                timebase: "ARFrame.timestamp seconds. videoPresentationTime = ARFrame.timestamp - first recorded ARFrame.timestamp.",
                matrixLayout: "row-major arrays exported from ARKit camera.transform and camera.intrinsics",
                pixelCoordinateSpace: "Pixel coordinates match ARFrame.camera.imageResolution for each frame."
            )

            metadataWriter = try MetadataWriter(url: metadataURL, sessionInfo: sessionInfo)
            state = .recording

            return RecordingStartInfo(
                sessionID: sessionID,
                videoURL: videoURL,
                metadataURL: metadataURL
            )
        }
    }

    func record(
        _ capture: ARFrameCapture,
        onProgress: @escaping (RecordingProgress) -> Void,
        onError: @escaping (Error) -> Void
    ) {
        queue.async {
            guard self.state == .recording else { return }

            do {
                try self.configureWriterIfNeeded(for: capture)
                guard let firstARTimestamp = self.firstARTimestamp,
                      let videoInput = self.videoInput,
                      let pixelBufferAdaptor = self.pixelBufferAdaptor,
                      let metadataWriter = self.metadataWriter else {
                    throw RecorderError.writerNotReady
                }

                let presentationSeconds = capture.timestamp - firstARTimestamp
                let presentationTime = CMTime(seconds: presentationSeconds, preferredTimescale: 1_000_000_000)

                guard presentationTime > self.lastPresentationTime else {
                    self.droppedFrameCount += 1
                    return
                }

                guard videoInput.isReadyForMoreMediaData else {
                    self.droppedFrameCount += 1
                    return
                }

                let appended = pixelBufferAdaptor.append(
                    capture.pixelBuffer,
                    withPresentationTime: presentationTime
                )

                guard appended else {
                    throw self.assetWriter?.error ?? RecorderError.appendFailed
                }

                self.lastPresentationTime = presentationTime

                let metadata = FrameMetadata(
                    frameIndex: self.frameCount,
                    arTimestamp: capture.timestamp,
                    videoPresentationTime: presentationSeconds,
                    cameraTransform: capture.cameraTransformRows,
                    cameraIntrinsics: capture.cameraIntrinsicsRows,
                    imageResolution: capture.imageResolution,
                    trackingState: capture.trackingState,
                    tapPoint: capture.tapPoint
                )

                try metadataWriter.append(metadata)
                self.frameCount += 1

                onProgress(
                    RecordingProgress(
                        frameCount: self.frameCount,
                        droppedFrameCount: self.droppedFrameCount
                    )
                )
            } catch {
                self.abortAfterFailure()
                onError(error)
            }
        }
    }

    func stop(completion: @escaping (Result<RecordingResult, Error>) -> Void) {
        queue.async {
            guard self.state != .idle else {
                completion(.failure(RecorderError.notRecording))
                return
            }

            let writer = self.assetWriter
            self.videoInput?.markAsFinished()

            let finishMetadataAndReset: (Error?) -> Void = { writerError in
                self.queue.async {
                    do {
                        let summary = RecordingSummary(
                            frameCount: self.frameCount,
                            droppedFrameCount: self.droppedFrameCount,
                            firstARTimestamp: self.firstARTimestamp,
                            lastVideoPresentationTime: self.lastPresentationTime.isValid ? self.lastPresentationTime.seconds : nil,
                            finishedAtISO8601: ISO8601DateFormatter().string(from: Date())
                        )
                        try self.metadataWriter?.finish(summary: summary)

                        if let writerError {
                            throw writerError
                        }

                        guard let outputURL = self.outputURL,
                              let metadataURL = self.metadataURL else {
                            throw RecorderError.missingOutputURL
                        }

                        let result = RecordingResult(
                            sessionID: self.sessionID,
                            videoURL: outputURL,
                            metadataURL: metadataURL,
                            frameCount: self.frameCount,
                            droppedFrameCount: self.droppedFrameCount
                        )

                        self.reset()
                        completion(.success(result))
                    } catch {
                        self.reset()
                        completion(.failure(error))
                    }
                }
            }

            if let writer {
                writer.finishWriting {
                    let error = writer.status == .failed ? writer.error : nil
                    finishMetadataAndReset(error)
                }
            } else {
                finishMetadataAndReset(nil)
            }
        }
    }

    private func configureWriterIfNeeded(for capture: ARFrameCapture) throws {
        guard assetWriter == nil else { return }
        guard let outputURL else { throw RecorderError.missingOutputURL }

        let width = CVPixelBufferGetWidth(capture.pixelBuffer)
        let height = CVPixelBufferGetHeight(capture.pixelBuffer)
        let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mov)

        let videoSettings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                AVVideoExpectedSourceFrameRateKey: 60,
                AVVideoMaxKeyFrameIntervalKey: 60,
                AVVideoAverageBitRateKey: max(width * height * 4, 8_000_000)
            ]
        ]

        let input = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
        input.expectsMediaDataInRealTime = true

        guard writer.canAdd(input) else {
            throw RecorderError.cannotAddVideoInput
        }

        writer.add(input)

        let sourceAttributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: CVPixelBufferGetPixelFormatType(capture.pixelBuffer),
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:]
        ]

        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: sourceAttributes
        )

        guard writer.startWriting() else {
            throw writer.error ?? RecorderError.startWritingFailed
        }

        writer.startSession(atSourceTime: .zero)

        assetWriter = writer
        videoInput = input
        pixelBufferAdaptor = adaptor
        firstARTimestamp = capture.timestamp
    }

    private func reset() {
        state = .idle
        assetWriter = nil
        videoInput = nil
        pixelBufferAdaptor = nil
        metadataWriter = nil
        outputURL = nil
        metadataURL = nil
        firstARTimestamp = nil
        lastPresentationTime = .negativeInfinity
        frameCount = 0
        droppedFrameCount = 0
        sessionID = ""
        deviceID = ""
    }

    private func abortAfterFailure() {
        state = .failed
        assetWriter?.cancelWriting()

        let summary = RecordingSummary(
            frameCount: frameCount,
            droppedFrameCount: droppedFrameCount,
            firstARTimestamp: firstARTimestamp,
            lastVideoPresentationTime: lastPresentationTime.isValid ? lastPresentationTime.seconds : nil,
            finishedAtISO8601: ISO8601DateFormatter().string(from: Date())
        )
        try? metadataWriter?.finish(summary: summary)

        reset()
    }

    static func recordingsDirectory() throws -> URL {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let directory = documents.appendingPathComponent("TriangometryRecordings", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private static let filenameDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        return formatter
    }()
}

struct RecordingStartInfo {
    let sessionID: String
    let videoURL: URL
    let metadataURL: URL
}

struct RecordingProgress {
    let frameCount: Int
    let droppedFrameCount: Int
}

struct RecordingResult {
    let sessionID: String
    let videoURL: URL
    let metadataURL: URL
    let frameCount: Int
    let droppedFrameCount: Int
}

enum RecorderError: LocalizedError {
    case alreadyRecording
    case notRecording
    case writerNotReady
    case missingOutputURL
    case cannotAddVideoInput
    case startWritingFailed
    case appendFailed

    var errorDescription: String? {
        switch self {
        case .alreadyRecording:
            return "Es läuft bereits ein Recording."
        case .notRecording:
            return "Es läuft kein Recording."
        case .writerNotReady:
            return "Der Video-Writer ist noch nicht bereit."
        case .missingOutputURL:
            return "Die Ausgabe-Datei fehlt."
        case .cannotAddVideoInput:
            return "Der Video-Input kann nicht zum AssetWriter hinzugefügt werden."
        case .startWritingFailed:
            return "Der AssetWriter konnte nicht starten."
        case .appendFailed:
            return "Der Pixelbuffer konnte nicht in das Video geschrieben werden."
        }
    }
}

extension FileManager {
    func removeItemIfExists(at url: URL) throws {
        guard fileExists(atPath: url.path) else { return }
        try removeItem(at: url)
    }
}

private extension String {
    func filenameSafe(defaultValue: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_-"))
        let scalars = unicodeScalars.map { allowed.contains($0) ? Character($0) : "_" }
        let value = String(scalars).trimmingCharacters(in: CharacterSet(charactersIn: "_-"))
        return value.isEmpty ? defaultValue : value
    }
}
