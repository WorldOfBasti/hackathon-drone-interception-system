import ARKit
import AVFoundation
import Foundation
import UIKit

final class ARSessionManager: NSObject, ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var recordedFrameCount = 0
    @Published private(set) var droppedFrameCount = 0
    @Published private(set) var statusText = "Bereit"
    @Published private(set) var lastTapText = ""
    @Published private(set) var lastRecording: RecordingResult?
    @Published private(set) var liveDebugData = LiveDebugData.placeholder
    @Published var alert: AppAlert?

    private let recorder = Recorder()
    private let tapLock = NSLock()
    private weak var session: ARSession?
    private var pendingTapPoint: PixelPoint?
    private var wantsRunningSession = false
    private var previousARFrameTimestamp: TimeInterval?
    private var latestFPS: Double = 0
    private var lastDebugPublishWallTime: TimeInterval = 0

    func attach(session: ARSession) {
        guard self.session !== session else { return }
        self.session = session
        session.delegate = self
        if wantsRunningSession {
            runWorldTracking()
        }
    }

    func startSession() {
        wantsRunningSession = true
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            runWorldTracking()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    granted ? self?.runWorldTracking() : self?.showCameraPermissionAlert()
                }
            }
        default:
            showCameraPermissionAlert()
        }
    }

    func pauseSession() {
        wantsRunningSession = false
        session?.pause()
    }

    func startRecording(deviceID: String) {
        guard !isRecording else { return }

        do {
            let startInfo = try recorder.start(deviceID: deviceID)
            recordedFrameCount = 0
            droppedFrameCount = 0
            lastRecording = nil
            isRecording = true
            statusText = "Recording \(startInfo.sessionID)"
        } catch {
            showError(title: "Recording konnte nicht starten", error: error)
        }
    }

    func stopRecording() {
        guard isRecording else { return }
        isRecording = false
        statusText = "Stoppe Recording"

        recorder.stop { [weak self] result in
            DispatchQueue.main.async {
                switch result {
                case .success(let recording):
                    self?.lastRecording = recording
                    self?.recordedFrameCount = recording.frameCount
                    self?.droppedFrameCount = recording.droppedFrameCount
                    self?.statusText = "Gespeichert"
                case .failure(let error):
                    self?.showError(title: "Recording konnte nicht gespeichert werden", error: error)
                }
            }
        }
    }

    func storeTap(at location: CGPoint, viewportSize: CGSize) {
        guard isRecording else { return }
        guard let frame = session?.currentFrame else { return }
        guard viewportSize.width > 0, viewportSize.height > 0 else { return }

        let orientation = activeInterfaceOrientation()
        let viewPoint = CGPoint(
            x: location.x / viewportSize.width,
            y: location.y / viewportSize.height
        )

        let imageTransform = frame.displayTransform(
            for: orientation,
            viewportSize: viewportSize
        ).inverted()

        let imagePoint = viewPoint.applying(imageTransform)
        let clampedX = min(max(imagePoint.x, 0), 1)
        let clampedY = min(max(imagePoint.y, 0), 1)
        let resolution = frame.camera.imageResolution

        let tapPoint = PixelPoint(
            u: Double(clampedX * resolution.width),
            v: Double(clampedY * resolution.height),
            normalizedX: Double(clampedX),
            normalizedY: Double(clampedY)
        )

        tapLock.lock()
        pendingTapPoint = tapPoint
        tapLock.unlock()

        lastTapText = String(format: "Tap u %.1f v %.1f", tapPoint.u, tapPoint.v)
    }

    private func runWorldTracking() {
        guard let session else {
            statusText = "ARView wird vorbereitet"
            return
        }

        guard ARWorldTrackingConfiguration.isSupported else {
            alert = AppAlert(
                title: "ARKit nicht unterstützt",
                message: "Dieses Gerät unterstützt ARWorldTrackingConfiguration nicht."
            )
            return
        }

        let configuration = ARWorldTrackingConfiguration()
        configuration.worldAlignment = .gravity
        configuration.isLightEstimationEnabled = false

        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        statusText = "ARSession läuft"
    }

    private func consumePendingTapPoint() -> PixelPoint? {
        tapLock.lock()
        defer { tapLock.unlock() }
        let tapPoint = pendingTapPoint
        pendingTapPoint = nil
        return tapPoint
    }

    private func activeInterfaceOrientation() -> UIInterfaceOrientation {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first(where: { $0.activationState == .foregroundActive })?
            .interfaceOrientation ?? .portrait
    }

    private func showCameraPermissionAlert() {
        alert = AppAlert(
            title: "Kamera-Zugriff fehlt",
            message: "Aktiviere den Kamera-Zugriff in den iOS-Einstellungen, damit ARKit Frames liefern kann."
        )
    }

    private func showError(title: String, error: Error) {
        alert = AppAlert(title: title, message: error.localizedDescription)
        statusText = "Fehler"
        isRecording = false
    }
}

extension ARSessionManager: ARSessionDelegate {
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        publishLiveDebugData(for: frame)

        guard isRecording else { return }

        let capture = ARFrameCapture(frame: frame, tapPoint: consumePendingTapPoint())
        recorder.record(capture) { [weak self] progress in
            guard progress.frameCount == 1 || progress.frameCount % 10 == 0 else { return }

            DispatchQueue.main.async {
                self?.recordedFrameCount = progress.frameCount
                self?.droppedFrameCount = progress.droppedFrameCount
            }
        } onError: { [weak self] error in
            DispatchQueue.main.async {
                self?.showError(title: "Frame konnte nicht geschrieben werden", error: error)
            }
        }
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        guard !isRecording else { return }
        DispatchQueue.main.async {
            self.statusText = camera.trackingState.metadataDescription
        }
    }

    private func publishLiveDebugData(for frame: ARFrame) {
        if let previousARFrameTimestamp {
            let delta = frame.timestamp - previousARFrameTimestamp
            if delta > 0 {
                latestFPS = 1 / delta
            }
        }
        previousARFrameTimestamp = frame.timestamp

        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastDebugPublishWallTime >= 0.12 else { return }
        lastDebugPublishWallTime = now

        let resolution = frame.camera.imageResolution
        let transform = frame.camera.transform
        let intrinsics = frame.camera.intrinsics
        let debugData = LiveDebugData(
            arTimestamp: frame.timestamp,
            fps: latestFPS,
            imageWidth: Int(resolution.width.rounded()),
            imageHeight: Int(resolution.height.rounded()),
            trackingState: frame.camera.trackingState.metadataDescription,
            cameraX: transform.columns.3.x,
            cameraY: transform.columns.3.y,
            cameraZ: transform.columns.3.z,
            fx: intrinsics.columns.0.x,
            fy: intrinsics.columns.1.y
        )

        DispatchQueue.main.async {
            self.liveDebugData = debugData
        }
    }
}

struct AppAlert: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

struct LiveDebugData {
    static let placeholder = LiveDebugData(
        arTimestamp: 0,
        fps: 0,
        imageWidth: 0,
        imageHeight: 0,
        trackingState: "waiting",
        cameraX: 0,
        cameraY: 0,
        cameraZ: 0,
        fx: 0,
        fy: 0
    )

    let arTimestamp: TimeInterval
    let fps: Double
    let imageWidth: Int
    let imageHeight: Int
    let trackingState: String
    let cameraX: Float
    let cameraY: Float
    let cameraZ: Float
    let fx: Float
    let fy: Float

    var shortTrackingState: String {
        if trackingState == "normal" {
            return "TRACK OK"
        }

        if trackingState == "notAvailable" {
            return "NO TRACK"
        }

        if trackingState.hasPrefix("limited.") {
            return "LIMITED"
        }

        return trackingState.uppercased()
    }
}
