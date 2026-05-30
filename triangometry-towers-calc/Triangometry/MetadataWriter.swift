import ARKit
import Foundation
import simd

final class MetadataWriter {
    private let fileHandle: FileHandle
    private let encoder: JSONEncoder
    private var hasWrittenFrame = false
    private var isFinished = false

    init(url: URL, sessionInfo: RecordingSessionInfo) throws {
        encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]

        FileManager.default.createFile(atPath: url.path, contents: nil)
        fileHandle = try FileHandle(forWritingTo: url)

        try writeString("{\"session\":")
        try writeEncoded(sessionInfo)
        try writeString(",\"frames\":[")
    }

    func append(_ frame: FrameMetadata) throws {
        guard !isFinished else { return }

        if hasWrittenFrame {
            try writeString(",")
        }

        try writeEncoded(frame)
        hasWrittenFrame = true
    }

    func finish(summary: RecordingSummary) throws {
        guard !isFinished else { return }
        isFinished = true
        try writeString("],\"summary\":")
        try writeEncoded(summary)
        try writeString("}\n")
        try fileHandle.close()
    }

    private func writeEncoded<T: Encodable>(_ value: T) throws {
        let data = try encoder.encode(value)
        fileHandle.write(data)
    }

    private func writeString(_ value: String) throws {
        guard let data = value.data(using: .utf8) else { return }
        fileHandle.write(data)
    }
}

struct RecordingSessionInfo: Codable {
    let sessionID: String
    let deviceID: String
    let createdAtISO8601: String
    let videoFilename: String
    let metadataFilename: String
    let timebase: String
    let matrixLayout: String
    let pixelCoordinateSpace: String
}

struct RecordingSummary: Codable {
    let frameCount: Int
    let droppedFrameCount: Int
    let firstARTimestamp: TimeInterval?
    let lastVideoPresentationTime: TimeInterval?
    let finishedAtISO8601: String
}

struct FrameMetadata: Codable {
    let frameIndex: Int
    let arTimestamp: TimeInterval
    let videoPresentationTime: TimeInterval
    let cameraTransform: [[Float]]
    let cameraIntrinsics: [[Float]]
    let imageResolution: ImageResolution
    let trackingState: String
    let tapPoint: PixelPoint?
}

struct ARFrameCapture {
    let timestamp: TimeInterval
    let pixelBuffer: CVPixelBuffer
    let cameraTransformRows: [[Float]]
    let cameraIntrinsicsRows: [[Float]]
    let imageResolution: ImageResolution
    let trackingState: String
    let tapPoint: PixelPoint?

    init(frame: ARFrame, tapPoint: PixelPoint?) {
        timestamp = frame.timestamp
        pixelBuffer = frame.capturedImage
        cameraTransformRows = frame.camera.transform.rowMajorArray
        cameraIntrinsicsRows = frame.camera.intrinsics.rowMajorArray
        imageResolution = ImageResolution(frame.camera.imageResolution)
        trackingState = frame.camera.trackingState.metadataDescription
        self.tapPoint = tapPoint
    }
}

struct ImageResolution: Codable {
    let width: Double
    let height: Double

    init(_ size: CGSize) {
        width = Double(size.width)
        height = Double(size.height)
    }
}

struct PixelPoint: Codable {
    let u: Double
    let v: Double
    let normalizedX: Double
    let normalizedY: Double
}

extension simd_float4x4 {
    var rowMajorArray: [[Float]] {
        [
            [columns.0.x, columns.1.x, columns.2.x, columns.3.x],
            [columns.0.y, columns.1.y, columns.2.y, columns.3.y],
            [columns.0.z, columns.1.z, columns.2.z, columns.3.z],
            [columns.0.w, columns.1.w, columns.2.w, columns.3.w]
        ]
    }
}

extension simd_float3x3 {
    var rowMajorArray: [[Float]] {
        [
            [columns.0.x, columns.1.x, columns.2.x],
            [columns.0.y, columns.1.y, columns.2.y],
            [columns.0.z, columns.1.z, columns.2.z]
        ]
    }
}

extension ARCamera.TrackingState {
    var metadataDescription: String {
        switch self {
        case .normal:
            return "normal"
        case .notAvailable:
            return "notAvailable"
        case .limited(let reason):
            return "limited.\(reason.metadataDescription)"
        @unknown default:
            return "unknown"
        }
    }
}

private extension ARCamera.TrackingState.Reason {
    var metadataDescription: String {
        switch self {
        case .initializing:
            return "initializing"
        case .excessiveMotion:
            return "excessiveMotion"
        case .insufficientFeatures:
            return "insufficientFeatures"
        case .relocalizing:
            return "relocalizing"
        @unknown default:
            return "unknown"
        }
    }
}
